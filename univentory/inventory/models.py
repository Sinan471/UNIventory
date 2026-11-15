"""Inventory records (owner: Jesher).

Asset, AssetPortion, AssetEvent and Attachment from the Phase 4-5 model.

* Asset holds identity, description, legal ownership, restrictions,
  acquisition facts and typed specifications.
* AssetPortion is the only place physical quantity lives. A portion is a set
  of interchangeable units sharing department, location, custodian,
  condition, lifecycle, safety and allocation (FR-06). Different subsets are
  split into linked portions; quantities are conserved.
* AssetEvent is the immutable ledger/history (FR-09, BR-17).
* Condition, safety, lifecycle and allocation are separate fields. There is
  no universal status field and no free status dropdown.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from identity.models import Category, Department, Location

KU_LEGAL_OWNER = "Khalifa University"


class TrackingType(models.TextChoices):
    INDIVIDUAL = "INDIVIDUAL", _("Individual item")
    BATCH = "BATCH", _("Quantity batch")


class Unit(models.TextChoices):
    EACH = "EA", _("each")
    SET = "SET", _("set")
    BOX = "BOX", _("box")
    KILOGRAM = "KG", _("kg")
    LITRE = "L", _("litre")
    METRE = "M", _("metre")

    @classmethod
    def countable(cls) -> set[str]:
        return {cls.EACH, cls.SET, cls.BOX}


class Condition(models.TextChoices):
    UNKNOWN = "UNKNOWN", _("Unknown - pending inspection")
    POOR = "POOR", _("Poor")
    FAIR = "FAIR", _("Fair")
    GOOD = "GOOD", _("Good")
    EXCELLENT = "EXCELLENT", _("Excellent")


class SafetyState(models.TextChoices):
    UNKNOWN = "UNKNOWN", _("Not yet cleared")
    CLEARED = "CLEARED", _("Cleared for reuse")
    RESTRICTED = "RESTRICTED", _("Restricted")


class Lifecycle(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    IN_USE = "IN_USE", _("In use")
    AVAILABLE = "AVAILABLE", _("Available")
    UNDER_INSPECTION = "UNDER_INSPECTION", _("Under inspection")
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE", _("Under maintenance")
    IN_TRANSIT = "IN_TRANSIT", _("In transit")
    RETIRED = "RETIRED", _("Retired")
    DONATED = "DONATED", _("Donated")
    RECOVERED = "RECOVERED", _("Components recovered")
    RECYCLED = "RECYCLED", _("Recycled")
    DISPOSED = "DISPOSED", _("Disposed")
    LOST = "LOST", _("Lost")

    @classmethod
    def final_states(cls) -> set[str]:
        return {cls.DONATED, cls.RECOVERED, cls.RECYCLED, cls.DISPOSED, cls.LOST}

    @classmethod
    def on_hand_states(cls) -> set[str]:
        return {cls.IN_USE, cls.AVAILABLE, cls.UNDER_INSPECTION, cls.UNDER_MAINTENANCE, cls.RETIRED, cls.DRAFT}


class Allocation(models.TextChoices):
    FREE = "FREE", _("No active claim")
    HELD = "HELD", _("Held")
    COMMITTED = "COMMITTED", _("Committed to transfer")
    FINAL_COMMITTED = "FINAL_COMMITTED", _("Committed to final action")
    SETTLED = "SETTLED", _("Claim settled")


class OwnershipRestriction(models.TextChoices):
    NONE = "NONE", _("None - owned outright by KU")
    LEASED = "LEASED", _("Leased")
    SPONSORED = "SPONSORED", _("Sponsored or grant-funded")
    LICENSED = "LICENSED", _("Licensed")
    OTHER = "OTHER", _("Other restriction")


class Provenance(models.TextChoices):
    OPERATIONAL = "OPERATIONAL", _("Authorised operational record")
    PUBLIC_EXAMPLE = "PUBLIC_EXAMPLE", _("Public example")
    SYNTHETIC = "SYNTHETIC", _("Synthetic (development data)")


class RecordStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    REGISTERED = "REGISTERED", _("Registered")


class Asset(models.Model):
    asset_code = models.CharField(_("asset ID"), max_length=24, unique=True, editable=False)
    tracking_type = models.CharField(_("tracking"), max_length=12, choices=TrackingType.choices)
    title = models.CharField(_("title"), max_length=160)
    description = models.TextField(_("description"))
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="assets")
    subcategory = models.CharField(_("subcategory"), max_length=80, blank=True)
    tags = models.JSONField(_("tags"), default=list, blank=True)
    material = models.CharField(_("main material"), max_length=120, blank=True)
    weight_kg = models.DecimalField(
        _("weight per unit (kg)"), max_digits=10, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit = models.CharField(_("unit"), max_length=4, choices=Unit.choices, default=Unit.EACH)
    registered_quantity = models.DecimalField(
        _("registered quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))]
    )

    # Ownership and responsibility. Legal owner, departmental allocation,
    # physical location and custody are separate (FR-10, BR-03).
    legal_owner = models.CharField(_("legal owner"), max_length=160, default=KU_LEGAL_OWNER)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="assets")
    custodian = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="custody_assets")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="assets")

    # Acquisition facts. Missing history is explicitly Unknown (FR-05).
    acquisition_date = models.DateField(_("purchase date"), null=True, blank=True)
    acquisition_date_unknown = models.BooleanField(_("purchase date unknown"), default=False)
    estimated_value_aed = models.DecimalField(
        _("estimated value (AED)"), max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    estimated_value_unknown = models.BooleanField(_("value unknown"), default=False)

    # Restrictions and handling (BR-13, NFR-06).
    ownership_restriction = models.CharField(
        _("ownership restriction"), max_length=12, choices=OwnershipRestriction.choices,
        default=OwnershipRestriction.NONE,
    )
    restriction_notes = models.TextField(_("restriction and release conditions"), blank=True)
    release_rights_confirmed = models.BooleanField(_("release rights confirmed"), default=False)
    is_hazardous = models.BooleanField(_("hazardous or contaminated"), default=False)
    is_data_bearing = models.BooleanField(_("stores data"), default=False)
    is_regulated = models.BooleanField(_("regulated item"), default=False)
    handling_notes = models.TextField(_("handling requirements"), blank=True)

    specifications = models.JSONField(_("specifications"), default=dict, blank=True)
    provenance = models.CharField(
        _("record source"), max_length=16, choices=Provenance.choices, default=Provenance.OPERATIONAL
    )
    record_status = models.CharField(max_length=12, choices=RecordStatus.choices, default=RecordStatus.DRAFT)
    parent_asset = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="recovered_children",
        help_text=_("Set for component-recovery child records."),
    )
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["department", "category"]),
            models.Index(fields=["custodian"]),
        ]

    def __str__(self) -> str:
        return f"{self.asset_code} {self.title}"

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Assets with history are never deleted (BR-17)."))

    @property
    def has_restriction(self) -> bool:
        return self.ownership_restriction != OwnershipRestriction.NONE

    @property
    def needs_handling(self) -> bool:
        return self.is_hazardous or self.is_data_bearing or self.is_regulated

    def quantity_display(self, qty) -> str:
        if self.unit in Unit.countable():
            return f"{int(qty)}"
        return f"{qty.normalize():f}"


class AssetPortion(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="portions")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    path = models.CharField(max_length=255, db_index=True, editable=False,
                            help_text="Materialised lineage '/root/child/'.")
    is_active_leaf = models.BooleanField(default=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="portions")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="portions")
    custodian = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="custody_portions")
    temporary_custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="transit_portions"
    )

    condition = models.CharField(max_length=10, choices=Condition.choices, default=Condition.UNKNOWN)
    lifecycle_state = models.CharField(max_length=20, choices=Lifecycle.choices, default=Lifecycle.DRAFT)
    safety_state = models.CharField(max_length=12, choices=SafetyState.choices, default=SafetyState.UNKNOWN)
    safety_evidence_ref = models.CharField(max_length=120, blank=True)

    allocation = models.CharField(max_length=16, choices=Allocation.choices, default=Allocation.FREE)
    claim_ref = models.CharField(max_length=64, blank=True, db_index=True,
                                 help_text="Owning case reference, e.g. reservation:12 or consignment:4.")
    listing_ref = models.PositiveBigIntegerField(null=True, blank=True, db_index=True,
                                                 help_text="Listing through which these units were claimed.")

    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=0), name="portion_quantity_not_negative"),
            models.CheckConstraint(
                condition=Q(allocation="FREE") | ~Q(claim_ref=""), name="claimed_portion_has_claim_ref"
            ),
        ]
        indexes = [
            models.Index(fields=["asset", "is_active_leaf"]),
            models.Index(fields=["lifecycle_state"]),
            # Free-quantity lookups for catalogue search (NFR-01).
            models.Index(fields=["asset", "department", "is_active_leaf", "lifecycle_state", "allocation"],
                         name="portion_free_lookup"),
        ]

    def __str__(self) -> str:
        return f"{self.asset.asset_code}#{self.pk} x{self.quantity}"

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Portions are part of the quantity ledger and cannot be deleted."))

    @property
    def is_reservable_unit(self) -> bool:
        return (
            self.is_active_leaf
            and self.lifecycle_state == Lifecycle.AVAILABLE
            and self.safety_state == SafetyState.CLEARED
            and self.allocation == Allocation.FREE
        )


class AssetEventType(models.TextChoices):
    REGISTERED = "REGISTERED", _("Registered")
    UPDATED = "UPDATED", _("Record updated")
    ACTIVATED = "ACTIVATED", _("Record activated")
    SPLIT = "SPLIT", _("Batch split")
    ADJUSTED = "ADJUSTED", _("Quantity adjusted")
    HELD = "HELD", _("Units held")
    COMMITTED = "COMMITTED", _("Hold committed")
    CLAIM_RELEASED = "CLAIM_RELEASED", _("Claim released")
    DISPATCHED = "DISPATCHED", _("Dispatched")
    RECEIVED = "RECEIVED", _("Accepted at destination")
    RETURNED = "RETURNED", _("Physically returned")
    LOST = "LOST", _("Authorised as lost")
    LIFECYCLE_CHANGED = "LIFECYCLE_CHANGED", _("Lifecycle changed")
    SAFETY_RECORDED = "SAFETY_RECORDED", _("Safety decision recorded")
    CONDITION_RECORDED = "CONDITION_RECORDED", _("Condition recorded")
    FINAL_COMMITTED = "FINAL_COMMITTED", _("Committed to final action")
    FINAL_EXECUTED = "FINAL_EXECUTED", _("Final action executed")
    RECOVERED_CHILD = "RECOVERED_CHILD", _("Recovered component recorded")
    EVIDENCE_ADDED = "EVIDENCE_ADDED", _("Evidence added")
    EVIDENCE_WITHDRAWN = "EVIDENCE_WITHDRAWN", _("Evidence withdrawn")
    LISTING = "LISTING", _("Listing change")


class AssetEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Asset events are immutable.")

    def delete(self):
        raise ValidationError("Asset events are immutable.")


class AssetEvent(models.Model):
    """Append-only ledger and lifecycle history entry."""

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="events")
    portion = models.ForeignKey(AssetPortion, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    related_portion = models.ForeignKey(
        AssetPortion, null=True, blank=True, on_delete=models.PROTECT, related_name="related_events"
    )
    event_type = models.CharField(max_length=20, choices=AssetEventType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    reference = models.CharField(max_length=64, blank=True, help_text="Workflow case or claim reference.")
    evidence_refs = models.JSONField(default=list, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    operation_key = models.CharField(max_length=64, blank=True, db_index=True)
    operation_name = models.CharField(max_length=40, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    objects = AssetEventQuerySet.as_manager()

    class Meta:
        ordering = ["occurred_at", "pk"]
        indexes = [models.Index(fields=["asset", "occurred_at"])]

    def __str__(self) -> str:
        return f"{self.asset_id} {self.event_type} {self.occurred_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Asset events are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Asset events are immutable.")


class AttachmentAccess(models.TextChoices):
    CATALOGUE_PHOTO = "CATALOGUE_PHOTO", _("Catalogue photo (visible on a published listing)")
    RESTRICTED = "RESTRICTED", _("Restricted evidence (asset staff only)")


class AttachmentStatus(models.TextChoices):
    ACCEPTED = "ACCEPTED", _("Accepted")
    QUARANTINED = "QUARANTINED", _("Quarantined")


class Attachment(models.Model):
    """Protected evidence metadata. Bytes live outside any public URL."""

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="attachments")
    context_ref = models.CharField(
        max_length=64, blank=True,
        help_text="Optional owning record in another module, e.g. receipt:9. Access still follows the asset.",
    )
    original_name = models.CharField(max_length=200)
    stored_name = models.CharField(max_length=255, unique=True, editable=False)
    content_type = models.CharField(max_length=40)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    access_class = models.CharField(max_length=16, choices=AttachmentAccess.choices, default=AttachmentAccess.RESTRICTED)
    status = models.CharField(max_length=12, choices=AttachmentStatus.choices, default=AttachmentStatus.ACCEPTED)
    status_reason = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.original_name

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Evidence is withdrawn, not deleted, so history is retained."))

    @property
    def is_image(self) -> bool:
        return self.content_type in {"image/jpeg", "image/png"}

    @property
    def is_available(self) -> bool:
        return self.status == AttachmentStatus.ACCEPTED and self.withdrawn_at is None

    @staticmethod
    def new_stored_name(extension: str) -> str:
        now = timezone.now()
        return f"{now:%Y/%m}/{uuid.uuid4().hex}{extension}"
