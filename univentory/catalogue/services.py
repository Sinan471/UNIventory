"""CatalogueService and CatalogueQueryService (owner: Jesher).

Listing transitions are Jesher's. Release *decisions* come from Sinan's
ApprovalService through the RELEASE_APPROVALS port; the catalogue never
records an approval itself. Holds placed through a listing go through the
InventoryLedger in the caller's transaction.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import (
    DecimalField,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Greatest, Least
from django.dispatch import receiver
from django.utils import timezone

from core.contracts import (
    ActorContext,
    HiddenRecord,
    NotPermitted,
    StaleVersion,
    StockConflict,
    ValidationFailed,
    get_adapter,
)
from core.contracts.approvals import ReleaseStatus
from core.contracts.audit import audit, audit_denied
from identity.policy import AccessPolicy
from inventory.ledger import ZERO, InventoryLedger, _quantity
from inventory.models import (
    Allocation,
    Asset,
    AssetEvent,
    AssetEventType,
    AssetPortion,
    Lifecycle,
    RecordStatus,
    SafetyState,
)
from inventory.services import asset_materially_changed
from catalogue.models import Listing, ListingState

DEC = DecimalField(max_digits=12, decimal_places=3)

# Allowed manual transitions (plan Section 10, Listing).
TRANSITIONS = {
    "submit": ({ListingState.DRAFT}, ListingState.AWAITING_RELEASE),
    "publish": ({ListingState.AWAITING_RELEASE}, ListingState.PUBLISHED),
    "pause": ({ListingState.PUBLISHED}, ListingState.PAUSED),
    "resume": ({ListingState.PAUSED}, ListingState.PUBLISHED),
    "withdraw": ({ListingState.DRAFT, ListingState.AWAITING_RELEASE, ListingState.PUBLISHED, ListingState.PAUSED},
                 ListingState.WITHDRAWN),
    "close": ({ListingState.PUBLISHED, ListingState.PAUSED}, ListingState.CLOSED),
}


# ---------------------------------------------------------------------------
# Quantity expressions
# ---------------------------------------------------------------------------
def reservable_portions(listing_or_outer, *, outer: bool = False):
    """Free, eligible units of the listing's asset in its source department.

    Units already claimed or received through this listing are excluded so a
    listing never offers the same unit twice.
    """
    if outer:
        asset, department, pk = OuterRef("asset_id"), OuterRef("department_id"), OuterRef("pk")
    else:
        asset, department, pk = listing_or_outer.asset_id, listing_or_outer.department_id, listing_or_outer.pk
    return AssetPortion.objects.filter(
        asset_id=asset,
        department_id=department,
        is_active_leaf=True,
        lifecycle_state=Lifecycle.AVAILABLE,
        safety_state=SafetyState.CLEARED,
        allocation=Allocation.FREE,
    ).filter(Q(listing_ref__isnull=True) | ~Q(listing_ref=pk))


def _sum_subquery(qs):
    return Coalesce(
        Subquery(qs.order_by().values("asset_id").annotate(s=Sum("quantity")).values("s")[:1], output_field=DEC),
        Value(Decimal("0"), output_field=DEC),
        output_field=DEC,
    )


def annotate_quantities(qs):
    claimed = AssetPortion.objects.filter(listing_ref=OuterRef("pk"), is_active_leaf=True)
    qs = qs.annotate(
        reservable_qty=_sum_subquery(reservable_portions(None, outer=True)),
        claimed_qty=_sum_subquery(claimed),
    )
    return qs.annotate(
        free_qty=Greatest(
            Least(F("offered_quantity") - F("claimed_qty"), F("reservable_qty"), output_field=DEC),
            Value(Decimal("0"), output_field=DEC),
            output_field=DEC,
        )
    )


class CatalogueService:
    # ------------------------------------------------------------------
    # Read helpers / contract for Sinan
    # ------------------------------------------------------------------
    @staticmethod
    def reservable_in_lot(listing: Listing) -> Decimal:
        return reservable_portions(listing).aggregate(s=Sum("quantity"))["s"] or ZERO

    @staticmethod
    def claimed_through(listing: Listing) -> Decimal:
        return (
            AssetPortion.objects.filter(listing_ref=listing.pk, is_active_leaf=True).aggregate(s=Sum("quantity"))["s"]
            or ZERO
        )

    @classmethod
    def free_quantity(cls, listing: Listing) -> Decimal:
        """Units a new reservation could hold right now (0 unless Published)."""
        if listing.state != ListingState.PUBLISHED:
            return ZERO
        return max(ZERO, min(listing.offered_quantity - cls.claimed_through(listing), cls.reservable_in_lot(listing)))

    @staticmethod
    def on_hand_releasable(asset: Asset, department_id: int) -> Decimal:
        """Unclaimed units in use or available that a custodian may offer."""
        return (
            AssetPortion.objects.filter(
                asset=asset, department_id=department_id, is_active_leaf=True, allocation=Allocation.FREE,
                lifecycle_state__in=[Lifecycle.IN_USE, Lifecycle.AVAILABLE],
            ).aggregate(s=Sum("quantity"))["s"]
            or ZERO
        )

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    @classmethod
    def publication_blockers(cls, listing: Listing, *, for_resume: bool = False) -> list[str]:
        """Every reason the listing cannot become available (FR-12)."""
        asset = listing.asset
        reasons: list[str] = []
        decision = get_adapter("RELEASE_APPROVALS").current_decision(listing=listing)
        if for_resume:
            if not (decision and decision.status == ReleaseStatus.APPROVED
                    and decision.listing_version == listing.released_version):
                reasons.append("The release approval is no longer current; submit the listing for release review.")
        elif not (decision and decision.is_current_approval_for(listing.pk, listing.version)):
            reasons.append("A current release approval from the owning Department Representative is required.")
        for field, label in (("title", "listing title"), ("public_description", "public description"),
                             ("collection_info", "collection information")):
            if not str(getattr(listing, field) or "").strip():
                reasons.append(f"The {label} is missing.")
        if asset.record_status != RecordStatus.REGISTERED:
            reasons.append("The asset record is still a draft; activate it first.")
        if not asset.portions.filter(is_active_leaf=True, department_id=listing.department_id).exclude(
                lifecycle_state__in=Lifecycle.final_states()).exists():
            reasons.append("The asset has no active units in this department.")
        if asset.has_restriction and not asset.release_rights_confirmed:
            reasons.append("Ownership or licence restrictions are unresolved; release rights must be confirmed.")
        lot = AssetPortion.objects.filter(asset=asset, department_id=listing.department_id, is_active_leaf=True,
                                          lifecycle_state=Lifecycle.AVAILABLE, allocation=Allocation.FREE)
        if not lot.exists():
            reasons.append("No units are recorded as Available; mark the offered units Available first.")
        elif not lot.filter(safety_state=SafetyState.CLEARED).exists():
            reasons.append("No offered unit has current safety clearance for reuse.")
        elif cls.reservable_in_lot(listing) <= ZERO:
            reasons.append("There is no free quantity to publish.")
        return reasons

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    @staticmethod
    def _locked(listing_id: int, expected_version=None) -> Listing:
        listing = Listing.objects.select_for_update().select_related("asset").filter(pk=listing_id).first()
        if listing is None:
            raise HiddenRecord()
        if expected_version is not None and int(expected_version) != listing.version:
            raise StaleVersion(next_action="Reload the listing to see its current state.")
        return listing

    @staticmethod
    def _record(actor, listing: Listing, action: str, before: str, reason: str = "") -> None:
        AssetEvent.objects.create(
            asset=listing.asset, event_type=AssetEventType.LISTING, reference=f"listing:{listing.pk}",
            details={"action": action, "from": before, "to": listing.state, "reason": reason,
                     "listing_version": listing.version},
            actor=actor.user, operation_key=actor.operation_key, operation_name=f"listing.{action}",
            correlation_id=actor.correlation_id,
        )
        audit(f"listing.{action}", listing, actor, before={"state": before}, after={"state": listing.state},
              reason=reason)

    @classmethod
    @transaction.atomic
    def create(cls, actor: ActorContext, *, asset: Asset, title: str, public_description: str, offered_quantity,
               collection_info: str) -> Listing:
        asset = Asset.objects.select_for_update().get(pk=asset.pk)
        if not AccessPolicy.can_edit_asset(actor.user, asset):
            audit_denied("listing.create", "Asset", asset.pk, actor, "not assigned custodian")
            raise NotPermitted("Only the assigned custodian can list this asset.")
        if actor.operation_key:
            prior = AssetEvent.objects.filter(operation_key=actor.operation_key, operation_name="listing.create").first()
            if prior is not None:
                return Listing.objects.get(pk=int(prior.reference.split(":")[1]))
        qty = _quantity(offered_quantity, asset.unit)
        releasable = cls.on_hand_releasable(asset, asset.department_id)
        errors = {}
        if qty > releasable:
            errors["offered_quantity"] = [f"Only {asset.quantity_display(releasable)} unclaimed units can be offered."]
        if not title.strip():
            errors["title"] = ["Required."]
        if not public_description.strip():
            errors["public_description"] = ["Required."]
        if not collection_info.strip():
            errors["collection_info"] = ["Required."]
        if errors:
            raise ValidationFailed("Please correct the highlighted fields.", field_errors=errors)
        if Listing.objects.filter(asset=asset, department=asset.department, state__in=ListingState.open_states()).exists():
            raise ValidationFailed("This asset already has an open listing for the department.")
        portion = asset.portions.filter(is_active_leaf=True, department=asset.department).order_by("pk").first()
        listing = Listing.objects.create(
            asset=asset, department=asset.department, portion=portion, title=title.strip(),
            public_description=public_description.strip(), offered_quantity=qty,
            collection_info=collection_info.strip(), created_by=actor.user,
        )
        cls._record(actor, listing, "create", "")
        return listing

    @classmethod
    @transaction.atomic
    def update_draft(cls, actor: ActorContext, listing_id: int, *, expected_version: int, **fields) -> Listing:
        listing = cls._locked(listing_id, expected_version)
        if not AccessPolicy.can_manage_listing(actor.user, listing):
            raise NotPermitted()
        if listing.state != ListingState.DRAFT:
            raise ValidationFailed("Only a draft listing can be edited. Withdraw it to make changes.")
        allowed = {"title", "public_description", "offered_quantity", "collection_info"}
        if set(fields) - allowed:
            raise ValidationFailed("Unsupported listing fields.")
        if "offered_quantity" in fields:
            qty = _quantity(fields["offered_quantity"], listing.asset.unit)
            if qty > cls.on_hand_releasable(listing.asset, listing.department_id):
                raise ValidationFailed("That is more than the unclaimed quantity.",
                                       field_errors={"offered_quantity": ["Too many units."]})
            fields["offered_quantity"] = qty
        for key, value in fields.items():
            setattr(listing, key, value.strip() if isinstance(value, str) else value)
        listing.version += 1
        listing.save()
        cls._record(actor, listing, "edit", ListingState.DRAFT)
        return listing

    @classmethod
    @transaction.atomic
    def transition(cls, actor: ActorContext, listing_id: int, action: str, *, expected_version: int,
                   reason: str = "") -> Listing:
        if action not in TRANSITIONS:
            raise ValidationFailed("Unknown listing action.")
        listing = cls._locked(listing_id, expected_version)
        if not AccessPolicy.can_manage_listing(actor.user, listing):
            audit_denied(f"listing.{action}", "Listing", listing_id, actor, "not assigned custodian")
            raise NotPermitted("Only the assigned custodian can change this listing.")
        sources, target = TRANSITIONS[action]
        cls.sync_release_outcome(listing)
        if listing.state not in sources:
            raise ValidationFailed(f"A {listing.get_state_display().lower()} listing cannot be {action}ed.")
        if action in {"pause", "withdraw", "close"} and not reason.strip():
            raise ValidationFailed("Give a reason.", field_errors={"reason": ["Required."]})
        before = listing.state
        port = get_adapter("RELEASE_APPROVALS")
        if action == "submit":
            listing.state = target
            listing.version += 1
            listing.state_reason = ""
            listing.save()
            listing.release_case_ref = port.request_release(listing=listing, actor=actor)
            listing.save(update_fields=["release_case_ref"])
        elif action == "publish":
            blockers = cls.publication_blockers(listing)
            if blockers:
                raise ValidationFailed("The listing cannot be published yet.", field_errors={"__all__": blockers})
            listing.released_version = listing.version
            listing.state = target
            listing.published_at = timezone.now()
            listing.state_reason = ""
            listing.version += 1
            listing.save()
        elif action == "resume":
            blockers = cls.publication_blockers(listing, for_resume=True)
            if blockers:
                raise ValidationFailed("The listing cannot resume yet.", field_errors={"__all__": blockers})
            listing.state = target
            listing.state_reason = ""
            listing.version += 1
            listing.save()
        else:
            # Pause, withdraw and close stop new holds; existing commitments
            # and history are retained (FR-13).
            listing.state = target
            listing.state_reason = reason.strip()[:255]
            listing.version += 1
            listing.save()
            if action == "withdraw" and before == ListingState.AWAITING_RELEASE:
                port.supersede(listing=listing, actor=actor, reason="Listing withdrawn")
        cls._record(actor, listing, action, before, reason)
        return listing

    @classmethod
    def sync_release_outcome(cls, listing: Listing) -> Listing:
        """A returned or rejected release sends the listing back to Draft with
        the decision retained in the approval history."""
        if listing.state != ListingState.AWAITING_RELEASE:
            return listing
        decision = get_adapter("RELEASE_APPROVALS").current_decision(listing=listing)
        if decision and decision.listing_version == listing.version and decision.status in (
            ReleaseStatus.RETURNED, ReleaseStatus.REJECTED
        ):
            with transaction.atomic():
                locked = Listing.objects.select_for_update().get(pk=listing.pk)
                if locked.state == ListingState.AWAITING_RELEASE:
                    locked.state = ListingState.DRAFT
                    locked.state_reason = f"Release {decision.status}: {decision.reason}"[:255]
                    locked.version += 1
                    locked.save()
                    AssetEvent.objects.create(
                        asset=locked.asset, event_type=AssetEventType.LISTING, reference=f"listing:{locked.pk}",
                        details={"action": f"release_{decision.status}", "from": ListingState.AWAITING_RELEASE,
                                 "to": ListingState.DRAFT, "reason": decision.reason, "case": decision.case_ref},
                        actor_id=decision.decided_by_id or locked.created_by_id,
                    )
                listing.refresh_from_db()
        return listing

    # ------------------------------------------------------------------
    # Hold contract for Sinan's ReservationService
    # ------------------------------------------------------------------
    @classmethod
    def hold(cls, actor: ActorContext, *, listing_id: int, quantity, claim_ref: str) -> list[int]:
        """Atomically hold units offered by a published listing.

        Must run inside the caller's transaction (the reservation approval).
        Locks the listing row so competing approvals serialise; exactly one
        of twenty racing approvals for the last unit succeeds (NFR-04).
        """
        listing = cls._locked(listing_id)
        if listing.state != ListingState.PUBLISHED:
            raise StockConflict("This listing is not accepting reservations.")
        blockers = cls.publication_blockers(listing, for_resume=True)
        if blockers:
            raise StockConflict("The listing is no longer eligible: " + " ".join(blockers))
        qty = _quantity(quantity, listing.asset.unit)
        if qty > cls.free_quantity(listing):
            raise StockConflict("The requested quantity is no longer available.")
        candidates = list(reservable_portions(listing).values_list("pk", flat=True))
        return InventoryLedger.claim(actor, candidate_portion_ids=candidates, quantity=qty, claim_ref=claim_ref,
                                     allocation=Allocation.HELD, listing_ref=listing.pk)


@receiver(asset_materially_changed)
def _supersede_on_material_change(sender, asset, actor, fields, **kwargs):
    """BR-08: a material change supersedes unexecuted release decisions."""
    port = get_adapter("RELEASE_APPROVALS")
    reason = "Material change to " + ", ".join(fields)
    for listing in Listing.objects.select_for_update().filter(
        asset=asset, state__in=[ListingState.AWAITING_RELEASE, ListingState.PUBLISHED]
    ):
        before = listing.state
        port.supersede(listing=listing, actor=actor, reason=reason)
        listing.state = ListingState.DRAFT if before == ListingState.AWAITING_RELEASE else ListingState.PAUSED
        listing.state_reason = (reason + "; release review required.")[:255]
        listing.version += 1
        listing.save()
        CatalogueService._record(actor, listing, "superseded", before, reason)


class CatalogueQueryService:
    """Search and filter (FR-19, FR-20). Scope is applied before counting."""

    SORTS = {
        "newest": ("-published_at", "-pk"),
        "title": ("title", "pk"),
        "free": ("-free_qty", "-pk"),
        "value_low": ("asset__estimated_value_aed", "pk"),
        "value_high": ("-asset__estimated_value_aed", "pk"),
    }
    AGE_BANDS = {
        "lt1": (0, 1),
        "1to3": (1, 3),
        "3to5": (3, 5),
        "gt5": (5, None),
    }

    @staticmethod
    def visible(user):
        if not AccessPolicy.can_browse_catalogue(user):
            return Listing.objects.none()
        return Listing.objects.filter(state=ListingState.PUBLISHED)

    @classmethod
    def search(cls, user, params: dict):
        qs = annotate_quantities(
            cls.visible(user).select_related(
                "asset", "asset__category", "asset__location", "department", "portion", "portion__location"
            )
        )
        keyword = (params.get("q") or "").strip()
        if keyword:
            for term in keyword.split()[:6]:
                qs = qs.filter(
                    Q(title__icontains=term) | Q(public_description__icontains=term)
                    | Q(asset__title__icontains=term) | Q(asset__description__icontains=term)
                    | Q(asset__asset_code__iexact=term) | Q(asset__tags__icontains=term)
                    | Q(asset__subcategory__icontains=term)
                )
        if params.get("category"):
            qs = qs.filter(asset__category_id=params["category"])
        if params.get("department"):
            qs = qs.filter(department_id=params["department"])
        if params.get("location"):
            qs = qs.filter(portion__location_id=params["location"])
        if params.get("condition"):
            qs = qs.filter(Exists(reservable_portions(None, outer=True).filter(condition=params["condition"])))
        if params.get("lifecycle"):
            qs = qs.filter(Exists(AssetPortion.objects.filter(
                asset_id=OuterRef("asset_id"), department_id=OuterRef("department_id"), is_active_leaf=True,
                lifecycle_state=params["lifecycle"])))
        if params.get("min_qty") not in (None, ""):
            qs = qs.filter(free_qty__gte=params["min_qty"])
        if params.get("availability", "available") == "available":
            qs = qs.filter(free_qty__gt=0)
        if params.get("value_min") not in (None, ""):
            qs = qs.filter(asset__estimated_value_aed__gte=params["value_min"])
        if params.get("value_max") not in (None, ""):
            qs = qs.filter(asset__estimated_value_aed__lte=params["value_max"])
        age = params.get("age")
        if age == "unknown":
            qs = qs.filter(asset__acquisition_date__isnull=True)
        elif age in cls.AGE_BANDS:
            low, high = cls.AGE_BANDS[age]
            today = timezone.localdate()
            qs = qs.filter(asset__acquisition_date__lte=today - timedelta(days=365 * low))
            if high is not None:
                qs = qs.filter(asset__acquisition_date__gt=today - timedelta(days=365 * high))
        return qs.order_by(*cls.SORTS.get(params.get("sort") or "newest", cls.SORTS["newest"]))

    @staticmethod
    def get_visible(user, listing_id: int) -> Listing:
        listing = annotate_quantities(
            Listing.objects.select_related("asset", "asset__category", "department", "portion__location")
        ).filter(pk=listing_id).first()
        if listing is None:
            raise HiddenRecord()
        if listing.state == ListingState.PUBLISHED and AccessPolicy.can_browse_catalogue(user):
            return listing
        if AccessPolicy.can_view_asset_record(user, listing.asset):
            return listing
        raise HiddenRecord()

    @staticmethod
    def page_size() -> int:
        return settings.UNIVENTORY_CATALOGUE_PAGE_SIZE
