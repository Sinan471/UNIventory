"""InventoryService, AssetQueryService and AttachmentService (owner: Jesher).

Views call these services; services validate, lock and persist inside one
transaction and append AssetEvents through the ledger.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import django.dispatch
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.contracts import (
    ActorContext,
    HiddenRecord,
    NotPermitted,
    StaleVersion,
    ValidationFailed,
)
from core.contracts.audit import audit, audit_denied
from identity.models import Category, Department, Location, Role
from identity.policy import AccessPolicy
from inventory.ledger import ZERO, InventoryLedger, _quantity
from inventory.models import (
    Allocation,
    Asset,
    AssetEvent,
    AssetEventType,
    AssetPortion,
    Attachment,
    AttachmentAccess,
    AttachmentStatus,
    Condition,
    Lifecycle,
    OwnershipRestriction,
    RecordStatus,
    SafetyState,
    TrackingType,
    Unit,
)

# Fired after a material change so the catalogue can supersede release
# decisions (BR-08) without inventory importing the catalogue.
asset_materially_changed = django.dispatch.Signal()

MATERIAL_FIELDS = {
    "ownership_restriction", "restriction_notes", "release_rights_confirmed", "is_hazardous", "is_data_bearing",
    "is_regulated", "handling_notes", "specifications", "category", "unit", "legal_owner",
}
EDITABLE_FIELDS = [
    "title", "description", "category", "subcategory", "tags", "material", "weight_kg", "legal_owner",
    "location", "acquisition_date", "acquisition_date_unknown", "estimated_value_aed", "estimated_value_unknown",
    "ownership_restriction", "restriction_notes", "release_rights_confirmed", "is_hazardous", "is_data_bearing",
    "is_regulated", "handling_notes", "specifications", "provenance",
]


def _serialise(value):
    if isinstance(value, (Decimal, date)):
        return str(value)
    if hasattr(value, "pk"):
        return value.pk
    return value


@dataclass
class AssetInput:
    """Validated values from the asset editor (or an import/recovery caller)."""

    title: str
    description: str
    category: Category
    department: Department
    location: Location
    tracking_type: str
    quantity: Decimal
    unit: str
    condition: str = Condition.UNKNOWN
    subcategory: str = ""
    tags: list | None = None
    material: str = ""
    weight_kg: Decimal | None = None
    legal_owner: str = "Khalifa University"
    acquisition_date: date | None = None
    acquisition_date_unknown: bool = False
    estimated_value_aed: Decimal | None = None
    estimated_value_unknown: bool = False
    ownership_restriction: str = OwnershipRestriction.NONE
    restriction_notes: str = ""
    release_rights_confirmed: bool = False
    is_hazardous: bool = False
    is_data_bearing: bool = False
    is_regulated: bool = False
    handling_notes: str = ""
    specifications: dict | None = None
    provenance: str = "OPERATIONAL"
    custodian: object | None = None


class SpecificationValidator:
    """Validate typed category specifications (DATA-01)."""

    @staticmethod
    def clean(category: Category, raw: dict) -> dict:
        errors: dict[str, list[str]] = {}
        cleaned: dict = {}
        for field in category.spec_schema:
            key, kind = field["key"], field["type"]
            value = raw.get(key)
            if value in (None, ""):
                continue
            try:
                if kind == "integer":
                    number = int(str(value))
                    if number < 0:
                        raise ValueError
                    cleaned[key] = number
                elif kind == "decimal":
                    number = Decimal(str(value))
                    if number < 0 or not number.is_finite():
                        raise InvalidOperation
                    cleaned[key] = str(number)
                elif kind == "boolean":
                    cleaned[key] = str(value).lower() in {"1", "true", "yes", "on"}
                else:
                    text = str(value).strip()
                    if len(text) > 200:
                        raise ValueError
                    cleaned[key] = text
            except (ValueError, InvalidOperation):
                errors[f"spec_{key}"] = [f"Enter a valid {kind} value for {field.get('label', key)}."]
        unknown = set(raw) - {f["key"] for f in category.spec_schema}
        if unknown:
            errors["specifications"] = ["Unknown specification fields: " + ", ".join(sorted(unknown))]
        if errors:
            raise ValidationFailed("Please correct the specification values.", field_errors=errors)
        return cleaned


class InventoryService:
    # ------------------------------------------------------------------
    # Validation shared by register and update
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_common(data: dict, *, is_new: bool) -> None:
        errors: dict[str, list[str]] = {}
        today = timezone.localdate()
        if not str(data.get("title", "")).strip():
            errors["title"] = ["Required."]
        if not str(data.get("description", "")).strip():
            errors["description"] = ["Required."]
        category = data.get("category")
        if category is not None and not category.is_active and is_new:
            errors["category"] = ["This category is inactive."]
        location = data.get("location")
        if location is not None and not location.is_active:
            errors["location"] = ["This location is inactive and cannot be selected for a new record or move."]
        acquired = data.get("acquisition_date")
        if acquired and acquired > today:
            errors["acquisition_date"] = ["The purchase date cannot be in the future."]
        if not acquired and not data.get("acquisition_date_unknown"):
            errors["acquisition_date"] = ["Enter the purchase date or mark it Unknown."]
        if acquired and data.get("acquisition_date_unknown"):
            errors["acquisition_date_unknown"] = ["Clear Unknown when a date is entered."]
        value = data.get("estimated_value_aed")
        if value is not None and value < 0:
            errors["estimated_value_aed"] = ["Value cannot be negative."]
        if value is None and not data.get("estimated_value_unknown"):
            errors["estimated_value_aed"] = ["Enter the estimated value in AED or mark it Unknown."]
        if value is not None and data.get("estimated_value_unknown"):
            errors["estimated_value_unknown"] = ["Clear Unknown when a value is entered."]
        weight = data.get("weight_kg")
        if weight is not None and weight < 0:
            errors["weight_kg"] = ["Weight cannot be negative."]
        restriction = data.get("ownership_restriction", OwnershipRestriction.NONE)
        if restriction != OwnershipRestriction.NONE and not str(data.get("restriction_notes", "")).strip():
            errors["restriction_notes"] = ["Describe the release conditions for a restricted item."]
        if (data.get("is_hazardous") or data.get("is_data_bearing") or data.get("is_regulated")) and not str(
            data.get("handling_notes", "")
        ).strip():
            errors["handling_notes"] = ["Record the handling, decontamination or data-erasure requirement."]
        if subcategory := data.get("subcategory"):
            if category is not None and category.subcategories and subcategory not in category.subcategories:
                errors["subcategory"] = ["Choose a subcategory of the selected category."]
        if errors:
            raise ValidationFailed("Please correct the highlighted fields.", field_errors=errors)

    @staticmethod
    def _clean_tags(tags) -> list[str]:
        out = []
        for tag in tags or []:
            text = re.sub(r"\s+", " ", str(tag)).strip().lower()[:40]
            if text and text not in out:
                out.append(text)
        return out[:20]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    @classmethod
    @transaction.atomic
    def register(cls, actor: ActorContext, data: AssetInput, *, activate_as: str | None = None) -> Asset:
        """Register an asset with its first portion (FR-05, FR-06)."""
        if actor.operation_key:
            prior = AssetEvent.objects.filter(
                operation_key=actor.operation_key, event_type=AssetEventType.REGISTERED
            ).first()
            if prior is not None:
                if prior.actor_id != actor.user_id:
                    raise ValidationFailed("This form was already submitted by someone else.")
                return prior.asset
        if not AccessPolicy.can_register_asset(actor.user, data.department):
            audit_denied("asset.register", "Asset", "-", actor, "no custodian grant for department")
            raise NotPermitted("You need the Asset Custodian role for this department.")
        values = data.__dict__.copy()
        cls._validate_common(values, is_new=True)
        if data.tracking_type not in TrackingType.values:
            raise ValidationFailed("Choose individual item or quantity batch.", field_errors={"tracking_type": ["Required."]})
        if data.unit not in Unit.values:
            raise ValidationFailed("Choose a unit.", field_errors={"unit": ["Required."]})
        quantity = _quantity(data.quantity, data.unit)
        if data.tracking_type == TrackingType.INDIVIDUAL and (quantity != 1 or data.unit not in Unit.countable()):
            raise ValidationFailed(
                "An individually tracked item has quantity one.",
                field_errors={"quantity": ["Must be 1 for an individual item."]},
            )
        custodian = data.custodian or actor.user
        if custodian != actor.user and not AccessPolicy.has_role(custodian, Role.CUSTODIAN, data.department):
            raise ValidationFailed("The custodian must hold the Asset Custodian role for this department.",
                                   field_errors={"custodian": ["Not a custodian of this department."]})
        specs = SpecificationValidator.clean(data.category, data.specifications or {})
        if activate_as not in (None, Lifecycle.IN_USE, Lifecycle.AVAILABLE):
            raise ValidationFailed("A new record is saved as Draft, In use or Available.")

        asset = Asset(
            asset_code=f"TMP-{actor.correlation_id[:16]}",
            tracking_type=data.tracking_type,
            title=data.title.strip(),
            description=data.description.strip(),
            category=data.category,
            subcategory=data.subcategory,
            tags=cls._clean_tags(data.tags),
            material=data.material,
            weight_kg=data.weight_kg,
            unit=data.unit,
            registered_quantity=quantity,
            legal_owner=data.legal_owner or "Khalifa University",
            department=data.department,
            custodian=custodian,
            location=data.location,
            acquisition_date=data.acquisition_date,
            acquisition_date_unknown=data.acquisition_date_unknown,
            estimated_value_aed=data.estimated_value_aed,
            estimated_value_unknown=data.estimated_value_unknown,
            ownership_restriction=data.ownership_restriction,
            restriction_notes=data.restriction_notes,
            release_rights_confirmed=data.release_rights_confirmed,
            is_hazardous=data.is_hazardous,
            is_data_bearing=data.is_data_bearing,
            is_regulated=data.is_regulated,
            handling_notes=data.handling_notes,
            specifications=specs,
            provenance=data.provenance,
            created_by=actor.user,
        )
        asset.save()
        asset.asset_code = f"KU-{timezone.localdate():%Y}-{asset.pk:06d}"
        Asset.objects.filter(pk=asset.pk).update(asset_code=asset.asset_code)

        portion = InventoryLedger.create_root_portion(
            asset, quantity=quantity, department=data.department, location=data.location, custodian=custodian,
            condition=data.condition,
        )
        AssetEvent.objects.create(
            asset=asset,
            portion=portion,
            event_type=AssetEventType.REGISTERED,
            quantity=quantity,
            details={"result": {"asset": asset.pk}, "tracking": data.tracking_type, "unit": data.unit},
            actor=actor.user,
            operation_key=actor.operation_key,
            operation_name="register",
            correlation_id=actor.correlation_id,
        )
        audit("asset.registered", asset, actor, after={"asset_code": asset.asset_code, "quantity": str(quantity)})
        if activate_as and custodian == actor.user:
            cls.activate(ActorContext(user=actor.user, correlation_id=actor.correlation_id), asset, activate_as)
            asset.refresh_from_db()
        return asset

    @classmethod
    @transaction.atomic
    def update(cls, actor: ActorContext, asset_id: int, changes: dict, *, expected_version: int) -> Asset:
        """Edit an assigned record with optimistic version checking (FR-07)."""
        asset = Asset.objects.select_for_update().filter(pk=asset_id).first()
        if asset is None:
            raise HiddenRecord()
        if not AccessPolicy.can_edit_asset(actor.user, asset):
            audit_denied("asset.update", "Asset", asset_id, actor, "not assigned custodian")
            raise NotPermitted("Only the assigned custodian can edit this record.")
        if int(expected_version) != asset.version:
            raise StaleVersion(next_action="Reload the record; your changes were not saved.")
        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise ValidationFailed("These fields cannot be edited here: " + ", ".join(sorted(unknown)))
        merged = {field: getattr(asset, field) for field in EDITABLE_FIELDS}
        merged.update(changes)
        cls._validate_common(merged, is_new=False)
        if "specifications" in changes:
            changes["specifications"] = SpecificationValidator.clean(merged["category"], changes["specifications"])
        if "tags" in changes:
            changes["tags"] = cls._clean_tags(changes["tags"])
        before, after = {}, {}
        for field, value in changes.items():
            old = getattr(asset, field)
            if old != value:
                before[field], after[field] = _serialise(old), _serialise(value)
                setattr(asset, field, value)
        if not after:
            return asset
        asset.version += 1
        asset.save()
        AssetEvent.objects.create(
            asset=asset, event_type=AssetEventType.UPDATED, details={"before": before, "after": after},
            actor=actor.user, operation_key=actor.operation_key, operation_name="update",
            correlation_id=actor.correlation_id,
        )
        audit("asset.updated", asset, actor, before=before, after=after)
        material = MATERIAL_FIELDS & set(after)
        if material:
            asset_materially_changed.send(sender=Asset, asset=asset, actor=actor, fields=sorted(material))
        return asset

    @classmethod
    @transaction.atomic
    def activate(cls, actor: ActorContext, asset: Asset, to_state: str) -> Asset:
        """Draft -> In use or Available once the record is complete."""
        asset = Asset.objects.select_for_update().get(pk=asset.pk)
        if not AccessPolicy.can_edit_asset(actor.user, asset):
            raise NotPermitted()
        if to_state not in (Lifecycle.IN_USE, Lifecycle.AVAILABLE):
            raise ValidationFailed("A draft becomes In use or Available.")
        cls._validate_common({f: getattr(asset, f) for f in EDITABLE_FIELDS}, is_new=False)
        drafts = list(asset.portions.filter(is_active_leaf=True, lifecycle_state=Lifecycle.DRAFT))
        if not drafts:
            raise ValidationFailed("This record has no draft quantity to activate.")
        for portion in drafts:
            InventoryLedger.change_lifecycle(
                ActorContext(user=actor.user, correlation_id=actor.correlation_id), portion.pk, to_state,
                reason="Record activated",
            )
        Asset.objects.filter(pk=asset.pk).update(record_status=RecordStatus.REGISTERED, version=asset.version + 1)
        AssetEvent.objects.create(asset=asset, event_type=AssetEventType.ACTIVATED, details={"to": to_state},
                                  actor=actor.user, correlation_id=actor.correlation_id)
        asset.refresh_from_db()
        return asset

    @classmethod
    def _owned_portion(cls, actor: ActorContext, portion_id: int) -> AssetPortion:
        portion = AssetPortion.objects.select_related("asset").filter(pk=portion_id).first()
        if portion is None:
            raise HiddenRecord()
        if not (AccessPolicy.can_edit_asset(actor.user, portion.asset) or (
            portion.custodian_id == actor.user.pk
            and AccessPolicy.has_role(actor.user, Role.CUSTODIAN, portion.department_id)
        )):
            raise NotPermitted("Only the responsible custodian can change this quantity.")
        return portion

    @classmethod
    @transaction.atomic
    def split_batch(cls, actor: ActorContext, portion_id: int, quantity, *, expected_version: int, reason: str = ""):
        portion = cls._owned_portion(actor, portion_id)
        if portion.asset.tracking_type != TrackingType.BATCH:
            raise ValidationFailed("Only quantity batches can be split.")
        return InventoryLedger.split(actor, portion_id, quantity, expected_version=expected_version, reason=reason)

    @classmethod
    @transaction.atomic
    def adjust_quantity(cls, actor: ActorContext, portion_id: int, new_quantity, *, reason: str,
                        expected_version: int, evidence_refs=None):
        cls._owned_portion(actor, portion_id)
        result = InventoryLedger.adjust(actor, portion_id, new_quantity, reason=reason, evidence_refs=evidence_refs,
                                        expected_version=expected_version)
        audit("inventory.adjusted", result, actor, reason=reason)
        return result

    @classmethod
    @transaction.atomic
    def set_use_state(cls, actor: ActorContext, portion_id: int, to_state: str, *, expected_version: int,
                      quantity=None):
        """Custodian move between In use and Available. Other transitions
        belong to the workflow that owns them (inspection, transfer, final)."""
        portion = cls._owned_portion(actor, portion_id)
        if to_state not in (Lifecycle.IN_USE, Lifecycle.AVAILABLE) or portion.lifecycle_state not in (
            Lifecycle.IN_USE, Lifecycle.AVAILABLE
        ):
            raise ValidationFailed("Custodians can switch units between In use and Available only.")
        return InventoryLedger.change_lifecycle(actor, portion_id, to_state, quantity=quantity,
                                                expected_version=expected_version, reason="Custodian update")

    @classmethod
    @transaction.atomic
    def create_recovered_asset(cls, actor: ActorContext, *, parent_asset: Asset, data: AssetInput,
                               final_action_ref: str) -> Asset:
        """Component recovery creates a linked child record (FR-43..47).

        Called by Sinan's FinalActionService after an approved recovery; the
        caller has already checked the actor's authority for that case.
        """
        if not final_action_ref:
            raise ValidationFailed("A recovered component must reference its final-action case.")
        data.provenance = parent_asset.provenance
        if data.custodian is None:
            data.custodian = parent_asset.custodian
        child = cls.register(actor, data) if AccessPolicy.can_register_asset(actor.user, data.department) else None
        if child is None:
            raise NotPermitted("Recovery records need a custodian for the receiving department.")
        Asset.objects.filter(pk=child.pk).update(parent_asset=parent_asset)
        AssetEvent.objects.create(
            asset=parent_asset, event_type=AssetEventType.RECOVERED_CHILD, reference=final_action_ref,
            details={"child": child.pk, "child_code": child.asset_code}, actor=actor.user,
            correlation_id=actor.correlation_id,
        )
        child.refresh_from_db()
        return child


class AssetQueryService:
    """Scoped read interface for every module (Section 9).

    Scope is applied before counts, search or AI retrieval.
    """

    @staticmethod
    def records_for(user):
        return (
            Asset.objects.filter(AccessPolicy.asset_record_scope(user))
            .distinct()
            .select_related("category", "department", "location", "custodian")
        )

    @staticmethod
    def get_record(user, asset_id: int) -> Asset:
        asset = Asset.objects.select_related("category", "department", "location", "custodian").filter(
            pk=asset_id
        ).first()
        if asset is None or not AccessPolicy.can_view_asset_record(user, asset):
            # Non-disclosing: a hidden record looks the same as a missing one.
            raise HiddenRecord()
        return asset

    @staticmethod
    def current_portions(asset):
        return (
            asset.portions.filter(is_active_leaf=True, quantity__gt=0)
            .select_related("department", "location", "custodian", "temporary_custodian")
            .order_by("pk")
        )

    @staticmethod
    def quantity_summary(asset) -> dict:
        portions = asset.portions.filter(is_active_leaf=True)

        def total(qs):
            return qs.aggregate(s=Sum("quantity"))["s"] or ZERO

        return {
            "total": total(portions),
            "on_hand": total(portions.filter(lifecycle_state__in=Lifecycle.on_hand_states())),
            "free": total(portions.filter(lifecycle_state=Lifecycle.AVAILABLE, safety_state=SafetyState.CLEARED,
                                          allocation=Allocation.FREE)),
            "held": total(portions.filter(allocation=Allocation.HELD)),
            "committed": total(portions.filter(allocation__in=[Allocation.COMMITTED, Allocation.FINAL_COMMITTED])
                               .exclude(lifecycle_state=Lifecycle.IN_TRANSIT)),
            "in_transit": total(portions.filter(lifecycle_state=Lifecycle.IN_TRANSIT)),
            "blocked": total(portions.filter(
                Q(lifecycle_state__in=[Lifecycle.UNDER_INSPECTION, Lifecycle.UNDER_MAINTENANCE])
                | Q(safety_state=SafetyState.RESTRICTED)
            ).exclude(lifecycle_state__in=Lifecycle.final_states())),
            "final": total(portions.filter(lifecycle_state__in=Lifecycle.final_states())),
        }

    @staticmethod
    def history(user, asset):
        if not AccessPolicy.can_view_asset_record(user, asset):
            raise HiddenRecord()
        return asset.events.select_related("actor", "portion").order_by("-occurred_at", "-pk")

    @staticmethod
    def portion_view(user, portion_id: int) -> dict:
        """Contract read for Sinan/Jessica: current version, free quantity,
        condition, safety and allocation of one permitted portion."""
        portion = AssetPortion.objects.select_related("asset").filter(pk=portion_id).first()
        if portion is None or not AccessPolicy.can_view_asset_record(user, portion.asset):
            raise HiddenRecord()
        return {
            "portion_id": portion.pk,
            "asset_id": portion.asset_id,
            "asset_code": portion.asset.asset_code,
            "version": portion.version,
            "quantity": portion.quantity,
            "unit": portion.asset.unit,
            "condition": portion.condition,
            "lifecycle_state": portion.lifecycle_state,
            "safety_state": portion.safety_state,
            "allocation": portion.allocation,
            "claim_ref": portion.claim_ref,
            "department_id": portion.department_id,
            "location_id": portion.location_id,
            "custodian_id": portion.custodian_id,
            "is_reservable_unit": portion.is_reservable_unit,
        }


# ---------------------------------------------------------------------------
# Attachments (FR-08, NFR-11)
# ---------------------------------------------------------------------------
SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}
PDF_ACTIVE_CONTENT = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/OpenAction", b"/AA")


def _sniff(head: bytes) -> str | None:
    for content_type, signatures in SIGNATURES.items():
        if any(head.startswith(sig) for sig in signatures):
            return content_type
    return None


def safe_filename(name: str) -> str:
    base = os.path.basename(name or "file").replace("\x00", "")
    base = re.sub(r"[^\w.\- ()]+", "_", base, flags=re.UNICODE).strip(" .")
    return (base or "file")[:150]


class AttachmentService:
    @staticmethod
    def storage_root() -> Path:
        return Path(settings.PROTECTED_MEDIA_ROOT)

    @classmethod
    def path_for(cls, attachment: Attachment) -> Path:
        root = cls.storage_root().resolve()
        path = (root / attachment.stored_name).resolve()
        if root not in path.parents:
            raise HiddenRecord()
        return path

    @classmethod
    def inspect(cls, data: bytes, declared_name: str) -> tuple[str, str, str]:
        """Return (content_type, status, reason). Raises for unsupported files."""
        limits = settings.UNIVENTORY_ATTACHMENTS
        if len(data) == 0:
            raise ValidationFailed("The file is empty.", field_errors={"file": ["Empty file."]})
        if len(data) > limits["MAX_BYTES"]:
            raise ValidationFailed("Files must be 10 MB or smaller.", field_errors={"file": ["Larger than 10 MB."]})
        content_type = _sniff(data[:16])
        if content_type not in limits["ALLOWED_TYPES"]:
            raise ValidationFailed("Only JPG, PNG and PDF files are accepted.",
                                   field_errors={"file": ["Unsupported or unrecognised file type."]})
        if content_type.startswith("image/"):
            from PIL import Image

            Image.MAX_IMAGE_PIXELS = 60_000_000
            try:
                with Image.open(io.BytesIO(data)) as img:
                    img.verify()
                with Image.open(io.BytesIO(data)) as img:
                    img.load()
                    expected = "JPEG" if content_type == "image/jpeg" else "PNG"
                    if img.format != expected:
                        return content_type, AttachmentStatus.QUARANTINED, "Image format does not match its content."
            except Exception:  # noqa: BLE001 - any decode failure means unreadable
                return content_type, AttachmentStatus.QUARANTINED, "The image could not be read."
        else:
            if b"%%EOF" not in data[-2048:]:
                return content_type, AttachmentStatus.QUARANTINED, "The PDF is incomplete or unreadable."
            if any(marker in data for marker in PDF_ACTIVE_CONTENT):
                return content_type, AttachmentStatus.QUARANTINED, "The PDF contains active content."
        return content_type, AttachmentStatus.ACCEPTED, ""

    @classmethod
    @transaction.atomic
    def store(cls, actor: ActorContext, asset: Asset, uploaded, *, access_class: str, description: str = "",
              context_ref: str = "") -> Attachment:
        asset = Asset.objects.select_for_update().get(pk=asset.pk)
        if not AccessPolicy.can_edit_asset(actor.user, asset):
            audit_denied("attachment.upload", "Asset", asset.pk, actor, "not assigned custodian")
            raise NotPermitted("Only the assigned custodian can add evidence.")
        if access_class not in AttachmentAccess.values:
            raise ValidationFailed("Choose who can see this file.", field_errors={"access_class": ["Required."]})
        current = asset.attachments.filter(withdrawn_at__isnull=True).count()
        if current >= settings.UNIVENTORY_ATTACHMENTS["MAX_FILES_PER_RECORD"]:
            raise ValidationFailed("A record can hold up to ten files. Withdraw one first.",
                                   field_errors={"file": ["Limit of ten files reached."]})
        if getattr(uploaded, "size", 0) > settings.UNIVENTORY_ATTACHMENTS["MAX_BYTES"]:
            raise ValidationFailed("Files must be 10 MB or smaller.", field_errors={"file": ["Larger than 10 MB."]})
        data = uploaded.read()
        content_type, status, reason = cls.inspect(data, uploaded.name)
        attachment = Attachment(
            asset=asset,
            context_ref=context_ref,
            original_name=safe_filename(uploaded.name),
            stored_name=Attachment.new_stored_name(EXTENSIONS[content_type]),
            content_type=content_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            access_class=access_class,
            status=status,
            status_reason=reason,
            description=description[:200],
            uploaded_by=actor.user,
        )
        path = cls.path_for(attachment)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as handle:
            handle.write(data)
        try:
            attachment.save()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        AssetEvent.objects.create(
            asset=asset, event_type=AssetEventType.EVIDENCE_ADDED, evidence_refs=[f"attachment:{attachment.pk}"],
            details={"name": attachment.original_name, "status": status, "access": access_class},
            actor=actor.user, operation_key=actor.operation_key, operation_name="attach",
            correlation_id=actor.correlation_id,
        )
        audit("attachment.stored", attachment, actor, after={"status": status, "sha256": attachment.sha256})
        return attachment

    @classmethod
    def can_download(cls, user, attachment: Attachment) -> bool:
        if not attachment.is_available:
            return False
        if AccessPolicy.can_view_asset_record(user, attachment.asset):
            return True
        if attachment.access_class == AttachmentAccess.CATALOGUE_PHOTO and AccessPolicy.can_browse_catalogue(user):
            from catalogue.models import Listing, ListingState

            return Listing.objects.filter(asset=attachment.asset, state=ListingState.PUBLISHED).exists()
        return False

    @classmethod
    def open_for(cls, user, attachment_id: int):
        attachment = Attachment.objects.select_related("asset").filter(pk=attachment_id).first()
        if attachment is None or not cls.can_download(user, attachment):
            if attachment is not None:
                audit_denied("attachment.download", "Attachment", attachment_id, user, "not permitted")
            raise HiddenRecord()
        path = cls.path_for(attachment)
        if not path.exists():
            raise HiddenRecord()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != attachment.sha256:
            raise HiddenRecord("The stored file failed its integrity check.")
        return attachment, path

    @classmethod
    @transaction.atomic
    def withdraw(cls, actor: ActorContext, attachment: Attachment, reason: str) -> Attachment:
        attachment = Attachment.objects.select_for_update().select_related("asset").get(pk=attachment.pk)
        if not AccessPolicy.can_edit_asset(actor.user, attachment.asset):
            raise NotPermitted()
        if not reason.strip():
            raise ValidationFailed("A reason is required.", field_errors={"reason": ["Required."]})
        if attachment.withdrawn_at:
            return attachment
        attachment.withdrawn_at = timezone.now()
        attachment.withdrawn_reason = reason[:200]
        attachment.save(update_fields=["withdrawn_at", "withdrawn_reason"])
        AssetEvent.objects.create(
            asset=attachment.asset, event_type=AssetEventType.EVIDENCE_WITHDRAWN,
            evidence_refs=[f"attachment:{attachment.pk}"], details={"reason": reason[:200]}, actor=actor.user,
            correlation_id=actor.correlation_id,
        )
        return attachment
