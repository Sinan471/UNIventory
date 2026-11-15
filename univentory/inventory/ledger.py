"""InventoryLedger: the only implementation of physical quantity changes.

Owner: Jesher. Contract consumers: Sinan (reservations, transfers, care and
final actions) through these methods only (plan Section 9).

Rules enforced here:

* Every method must run inside the caller's ``transaction.atomic`` block, so
  workflow, ledger, audit and outbox writes commit or roll back together
  (NFR-15).
* Portions are locked (``select_for_update``) and then updated with a
  version guard, so two competing commands cannot both claim one unit
  (NFR-04, BR-05).
* Quantities are conserved: splits move quantity between linked portions;
  nothing is created or destroyed except through an evidenced adjustment.
* Every change appends an immutable AssetEvent naming actor, reference and
  operation key. Repeating an operation key with the same input returns the
  original result; reusing it for different input is rejected.
* Holding or committing units changes allocation, never physical location.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from django.db import connection, transaction
from django.db.models import F, Sum

from core.contracts import (
    ActorContext,
    DuplicateOperationConflict,
    StaleVersion,
    StockConflict,
    ValidationFailed,
)
from inventory.models import (
    Allocation,
    AssetEvent,
    AssetEventType,
    AssetPortion,
    Lifecycle,
    SafetyState,
    Unit,
)

ZERO = Decimal("0")

# Lifecycle transitions callable through ``change_lifecycle``. Transit
# outcomes and final outcomes have dedicated methods.
LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    Lifecycle.DRAFT: {Lifecycle.IN_USE, Lifecycle.AVAILABLE},
    Lifecycle.IN_USE: {Lifecycle.AVAILABLE, Lifecycle.UNDER_INSPECTION, Lifecycle.RETIRED},
    Lifecycle.AVAILABLE: {Lifecycle.IN_USE, Lifecycle.UNDER_INSPECTION, Lifecycle.RETIRED},
    Lifecycle.UNDER_INSPECTION: {
        Lifecycle.IN_USE, Lifecycle.AVAILABLE, Lifecycle.UNDER_MAINTENANCE, Lifecycle.RETIRED,
    },
    Lifecycle.UNDER_MAINTENANCE: {Lifecycle.IN_USE, Lifecycle.AVAILABLE, Lifecycle.UNDER_INSPECTION},
    Lifecycle.RETIRED: {Lifecycle.UNDER_INSPECTION},
}
# Transitions allowed while units carry an active claim. A safety or
# inspection block overlays a claim; it never silently releases it (NFR-07).
CLAIMED_TRANSITIONS = {Lifecycle.UNDER_INSPECTION}
FINAL_OUTCOMES = {Lifecycle.DONATED, Lifecycle.RECOVERED, Lifecycle.RECYCLED, Lifecycle.DISPOSED}
RECEIPT_STATES = {Lifecycle.IN_USE, Lifecycle.AVAILABLE}


def _require_transaction() -> None:
    if not connection.in_atomic_block:
        raise RuntimeError("InventoryLedger methods must run inside the caller's transaction.atomic block.")


def _quantity(value, unit: str) -> Decimal:
    try:
        qty = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - any parse failure is a validation error
        raise ValidationFailed("Enter a valid quantity.", field_errors={"quantity": ["Invalid number."]}) from exc
    if qty <= ZERO:
        raise ValidationFailed("Quantity must be greater than zero.", field_errors={"quantity": ["Must be positive."]})
    if unit in Unit.countable() and qty != qty.to_integral_value():
        raise ValidationFailed("Counted units must be whole numbers.", field_errors={"quantity": ["Whole units only."]})
    return qty


class InventoryLedger:
    # ------------------------------------------------------------------
    # Operation keys
    # ------------------------------------------------------------------
    @staticmethod
    def _replay(actor: ActorContext, operation: str, payload: dict):
        """Return the stored result for a repeated command, or None."""
        if not actor.operation_key:
            return None
        first = AssetEvent.objects.filter(operation_key=actor.operation_key).order_by("pk").first()
        if first is None:
            return None
        if (
            first.operation_name != operation
            or first.actor_id != actor.user_id
            or first.payload_hash != ActorContext.payload_hash(payload)
        ):
            raise DuplicateOperationConflict()
        return first.details.get("result")

    @staticmethod
    def _event(actor: ActorContext, operation: str, payload: dict, *, portion, event_type, quantity=None,
               related=None, reference="", details=None, evidence_refs=None, result=None) -> AssetEvent:
        data = dict(details or {})
        if result is not None:
            data["result"] = result
        return AssetEvent.objects.create(
            asset_id=portion.asset_id,
            portion=portion,
            related_portion=related,
            event_type=event_type,
            quantity=quantity,
            details=data,
            reference=reference,
            evidence_refs=list(evidence_refs or []),
            actor=actor.user,
            operation_key=actor.operation_key,
            operation_name=operation,
            payload_hash=ActorContext.payload_hash(payload),
            correlation_id=actor.correlation_id,
        )

    # ------------------------------------------------------------------
    # Locking and guarded writes
    # ------------------------------------------------------------------
    @staticmethod
    def _lock(ids: Iterable[int]) -> list[AssetPortion]:
        ids = sorted(set(ids))
        rows = list(
            AssetPortion.objects.select_for_update().select_related("asset").filter(pk__in=ids).order_by("pk")
        )
        if len(rows) != len(ids):
            raise StockConflict("One or more portions no longer exist.")
        return rows

    @staticmethod
    def _check_version(portion: AssetPortion, expected_version) -> None:
        if expected_version is not None and int(expected_version) != portion.version:
            raise StaleVersion()

    @staticmethod
    def _guarded_update(portion: AssetPortion, **changes) -> None:
        """Compare-and-set on version; a concurrent change raises StockConflict."""
        updated = AssetPortion.objects.filter(pk=portion.pk, version=portion.version).update(
            version=F("version") + 1, **changes
        )
        if updated != 1:
            raise StockConflict()
        for key, value in changes.items():
            setattr(portion, key, value)
        portion.version += 1

    @classmethod
    def _split_locked(cls, portion: AssetPortion, quantity: Decimal, **child_overrides) -> AssetPortion:
        """Move ``quantity`` from a locked portion into a new linked child."""
        if quantity > portion.quantity:
            raise StockConflict("Not enough units in this portion.")
        if quantity == portion.quantity:
            if child_overrides:
                cls._guarded_update(portion, **child_overrides)
            return portion
        cls._guarded_update(portion, quantity=portion.quantity - quantity)
        fields = {
            "asset_id": portion.asset_id,
            "parent": portion,
            "quantity": quantity,
            "department_id": portion.department_id,
            "location_id": portion.location_id,
            "custodian_id": portion.custodian_id,
            "temporary_custodian_id": portion.temporary_custodian_id,
            "condition": portion.condition,
            "lifecycle_state": portion.lifecycle_state,
            "safety_state": portion.safety_state,
            "safety_evidence_ref": portion.safety_evidence_ref,
            "allocation": portion.allocation,
            "claim_ref": portion.claim_ref,
            "listing_ref": portion.listing_ref,
            "path": "",
        }
        fields.update(child_overrides)
        child = AssetPortion.objects.create(**fields)
        AssetPortion.objects.filter(pk=child.pk).update(path=f"{portion.path}{child.pk}/")
        child.path = f"{portion.path}{child.pk}/"
        return child

    # ------------------------------------------------------------------
    # Root portion (used by InventoryService.register)
    # ------------------------------------------------------------------
    @staticmethod
    def create_root_portion(asset, *, quantity, department, location, custodian, condition) -> AssetPortion:
        _require_transaction()
        portion = AssetPortion.objects.create(
            asset=asset,
            quantity=quantity,
            department=department,
            location=location,
            custodian=custodian,
            condition=condition,
            lifecycle_state=Lifecycle.DRAFT,
            path="",
        )
        AssetPortion.objects.filter(pk=portion.pk).update(path=f"/{portion.pk}/")
        portion.path = f"/{portion.pk}/"
        return portion

    # ------------------------------------------------------------------
    # Splits and adjustments
    # ------------------------------------------------------------------
    @classmethod
    def split(cls, actor: ActorContext, portion_id: int, quantity, *, expected_version=None, reason: str = ""):
        _require_transaction()
        payload = {"portion": portion_id, "quantity": str(quantity)}
        if (replayed := cls._replay(actor, "split", payload)) is not None:
            return AssetPortion.objects.get(pk=replayed["portion"]), AssetPortion.objects.get(pk=replayed["child"])
        (portion,) = cls._lock([portion_id])
        cls._check_version(portion, expected_version)
        qty = _quantity(quantity, portion.asset.unit)
        if not portion.is_active_leaf or portion.allocation != Allocation.FREE:
            raise StockConflict("Only unclaimed current portions can be split.")
        if portion.lifecycle_state in Lifecycle.final_states() or portion.lifecycle_state == Lifecycle.IN_TRANSIT:
            raise StockConflict("Portions in transit or with a final outcome cannot be split.")
        if qty >= portion.quantity:
            raise ValidationFailed(
                "A split must leave at least one unit in the original portion.",
                field_errors={"quantity": ["Must be less than the portion quantity."]},
            )
        child = cls._split_locked(portion, qty)
        cls._event(actor, "split", payload, portion=portion, related=child, event_type=AssetEventType.SPLIT,
                   quantity=qty, details={"reason": reason, "remaining": str(portion.quantity)},
                   result={"portion": portion.pk, "child": child.pk})
        return portion, child

    @classmethod
    def adjust(cls, actor: ActorContext, portion_id: int, new_quantity, *, reason: str, evidence_refs=None,
               expected_version=None) -> AssetPortion:
        """Reconciled stock-count correction. Only unclaimed units can change."""
        _require_transaction()
        if not reason.strip():
            raise ValidationFailed("An adjustment needs a reason.", field_errors={"reason": ["Required."]})
        payload = {"portion": portion_id, "new_quantity": str(new_quantity)}
        if (replayed := cls._replay(actor, "adjust", payload)) is not None:
            return AssetPortion.objects.get(pk=replayed["portion"])
        (portion,) = cls._lock([portion_id])
        cls._check_version(portion, expected_version)
        try:
            new_qty = Decimal(str(new_quantity))
        except Exception as exc:  # noqa: BLE001
            raise ValidationFailed("Enter a valid quantity.", field_errors={"quantity": ["Invalid number."]}) from exc
        if new_qty < ZERO:
            raise ValidationFailed("Quantity cannot be negative.", field_errors={"quantity": ["Cannot be negative."]})
        if portion.asset.unit in Unit.countable() and new_qty != new_qty.to_integral_value():
            raise ValidationFailed("Counted units must be whole numbers.", field_errors={"quantity": ["Whole units only."]})
        if portion.allocation != Allocation.FREE:
            raise StockConflict("Stock cannot be reduced below its commitments; release the claim first.")
        if portion.asset.tracking_type == "INDIVIDUAL" and new_qty not in (ZERO, Decimal("1")):
            raise ValidationFailed("An individual item has quantity one.", field_errors={"quantity": ["Must be 1."]})
        before = portion.quantity
        cls._guarded_update(portion, quantity=new_qty)
        cls._event(actor, "adjust", payload, portion=portion, event_type=AssetEventType.ADJUSTED,
                   quantity=new_qty - before, evidence_refs=evidence_refs,
                   details={"before": str(before), "after": str(new_qty), "reason": reason},
                   result={"portion": portion.pk})
        return portion

    # ------------------------------------------------------------------
    # Claims: hold, commit, release (BR-04 to BR-06)
    # ------------------------------------------------------------------
    @classmethod
    def claim(cls, actor: ActorContext, *, candidate_portion_ids: Iterable[int], quantity, claim_ref: str,
              allocation: str = Allocation.HELD, listing_ref: int | None = None) -> list[int]:
        """Atomically claim ``quantity`` free, eligible units from candidates.

        Reuse holds need AVAILABLE + CLEARED units. Final-action commitments
        accept any unclaimed on-hand units (unsafe items may still have an
        authorised disposal route).
        """
        _require_transaction()
        if allocation not in {Allocation.HELD, Allocation.FINAL_COMMITTED}:
            raise ValidationFailed("Claims start as a hold or a final-action commitment.")
        if not claim_ref:
            raise ValidationFailed("A claim reference is required.")
        candidates = sorted(set(candidate_portion_ids))
        payload = {"candidates": candidates, "quantity": str(quantity), "claim": claim_ref, "allocation": allocation}
        if (replayed := cls._replay(actor, "claim", payload)) is not None:
            return replayed["portions"]
        if AssetPortion.objects.filter(claim_ref=claim_ref, is_active_leaf=True).exists():
            raise StockConflict("This case already holds units; a claim cannot be reused.")
        rows = cls._lock(candidates)
        if not rows:
            raise StockConflict()
        qty = _quantity(quantity, rows[0].asset.unit)

        def eligible(p: AssetPortion) -> bool:
            if not p.is_active_leaf or p.allocation != Allocation.FREE or p.quantity <= ZERO:
                return False
            if allocation == Allocation.HELD:
                return p.lifecycle_state == Lifecycle.AVAILABLE and p.safety_state == SafetyState.CLEARED
            return p.lifecycle_state in Lifecycle.on_hand_states() - {Lifecycle.DRAFT}

        pool = [p for p in rows if eligible(p)]
        if sum((p.quantity for p in pool), ZERO) < qty:
            raise StockConflict("The requested quantity is no longer available.")
        remaining = qty
        claimed: list[AssetPortion] = []
        for portion in pool:
            if remaining <= ZERO:
                break
            take = min(remaining, portion.quantity)
            part = cls._split_locked(
                portion, take, allocation=allocation, claim_ref=claim_ref, listing_ref=listing_ref
            )
            claimed.append(part)
            remaining -= take
        event_type = AssetEventType.HELD if allocation == Allocation.HELD else AssetEventType.FINAL_COMMITTED
        result = {"portions": [p.pk for p in claimed]}
        for index, part in enumerate(claimed):
            cls._event(actor, "claim", payload, portion=part, event_type=event_type, quantity=part.quantity,
                       reference=claim_ref, details={"listing": listing_ref},
                       result=result if index == 0 else None)
        return result["portions"]

    @classmethod
    def commit(cls, actor: ActorContext, *, claim_ref: str) -> list[int]:
        """Held -> Committed on transfer approval; ends normal hold expiry."""
        _require_transaction()
        payload = {"claim": claim_ref}
        if (replayed := cls._replay(actor, "commit", payload)) is not None:
            return replayed["portions"]
        ids = list(AssetPortion.objects.filter(claim_ref=claim_ref, is_active_leaf=True).values_list("pk", flat=True))
        rows = cls._lock(ids)
        held = [p for p in rows if p.allocation == Allocation.HELD]
        if not held or len(held) != len(rows):
            raise StockConflict("There is no active hold to commit for this case.")
        for p in held:
            if p.safety_state != SafetyState.CLEARED or p.lifecycle_state != Lifecycle.AVAILABLE:
                raise StockConflict("Held units are blocked by a safety or inspection change; review is required.")
        result = {"portions": [p.pk for p in held]}
        for index, p in enumerate(held):
            cls._guarded_update(p, allocation=Allocation.COMMITTED)
            cls._event(actor, "commit", payload, portion=p, event_type=AssetEventType.COMMITTED, quantity=p.quantity,
                       reference=claim_ref, result=result if index == 0 else None)
        return result["portions"]

    @classmethod
    def release_claim(cls, actor: ActorContext, *, claim_ref: str, quantity=None, reason: str = "") -> Decimal:
        """Release undispatched held/committed units once (expiry, cancellation).

        Units already dispatched are not touched: they need receipt, return
        or discrepancy resolution (BR-06).
        """
        _require_transaction()
        payload = {"claim": claim_ref, "quantity": str(quantity)}
        if (replayed := cls._replay(actor, "release", payload)) is not None:
            return Decimal(replayed["released"])
        ids = list(AssetPortion.objects.filter(claim_ref=claim_ref, is_active_leaf=True).values_list("pk", flat=True))
        rows = [
            p for p in cls._lock(ids)
            if p.allocation in {Allocation.HELD, Allocation.COMMITTED, Allocation.FINAL_COMMITTED}
            and p.lifecycle_state != Lifecycle.IN_TRANSIT
        ]
        available = sum((p.quantity for p in rows), ZERO)
        target = available if quantity is None else _quantity(quantity, rows[0].asset.unit if rows else Unit.EACH)
        if target > available:
            raise StockConflict("Cannot release more units than the case still claims on hand.")
        remaining = target
        first = True
        for portion in rows:
            if remaining <= ZERO:
                break
            take = min(remaining, portion.quantity)
            part = cls._split_locked(portion, take, allocation=Allocation.FREE, claim_ref="", listing_ref=None)
            cls._event(actor, "release", payload, portion=part, event_type=AssetEventType.CLAIM_RELEASED,
                       quantity=take, reference=claim_ref, details={"reason": reason},
                       result={"released": str(target)} if first else None)
            first = False
            remaining -= take
        if first:  # nothing to release: still record the idempotent outcome
            return ZERO
        return target

    # ------------------------------------------------------------------
    # Transfer movements (FR-31 to FR-36)
    # ------------------------------------------------------------------
    @classmethod
    def dispatch(cls, actor: ActorContext, *, claim_ref: str, quantity, consignment_ref: str,
                 temporary_custodian) -> list[int]:
        """Move committed units out of source on-hand stock into transit once."""
        _require_transaction()
        payload = {"claim": claim_ref, "quantity": str(quantity), "consignment": consignment_ref}
        if (replayed := cls._replay(actor, "dispatch", payload)) is not None:
            return replayed["portions"]
        if AssetPortion.objects.filter(claim_ref=consignment_ref, is_active_leaf=True).exists():
            raise StockConflict("This consignment has already been dispatched.")
        ids = list(AssetPortion.objects.filter(claim_ref=claim_ref, is_active_leaf=True).values_list("pk", flat=True))
        rows = [p for p in cls._lock(ids) if p.allocation == Allocation.COMMITTED
                and p.lifecycle_state == Lifecycle.AVAILABLE]
        if not rows:
            raise StockConflict("There are no committed units to dispatch.")
        if any(p.safety_state != SafetyState.CLEARED for p in rows):
            raise StockConflict("Units without current safety clearance cannot be dispatched (NFR-05).")
        qty = _quantity(quantity, rows[0].asset.unit)
        if qty > sum((p.quantity for p in rows), ZERO):
            raise StockConflict("Cannot dispatch more than the committed quantity.")
        remaining = qty
        moved = []
        for portion in rows:
            if remaining <= ZERO:
                break
            take = min(remaining, portion.quantity)
            part = cls._split_locked(
                portion, take, lifecycle_state=Lifecycle.IN_TRANSIT, claim_ref=consignment_ref,
                temporary_custodian_id=getattr(temporary_custodian, "pk", temporary_custodian),
            )
            moved.append(part)
            remaining -= take
        result = {"portions": [p.pk for p in moved]}
        for index, part in enumerate(moved):
            cls._event(actor, "dispatch", payload, portion=part, event_type=AssetEventType.DISPATCHED,
                       quantity=part.quantity, reference=consignment_ref,
                       details={"transfer_claim": claim_ref, "temporary_custodian": part.temporary_custodian_id},
                       result=result if index == 0 else None)
        return result["portions"]

    @classmethod
    def _transit_rows(cls, consignment_ref: str) -> list[AssetPortion]:
        ids = list(AssetPortion.objects.filter(claim_ref=consignment_ref, is_active_leaf=True)
                   .values_list("pk", flat=True))
        return [p for p in cls._lock(ids) if p.lifecycle_state == Lifecycle.IN_TRANSIT]

    @classmethod
    def accept_receipt(cls, actor: ActorContext, *, consignment_ref: str, quantity, department, location, custodian,
                       lifecycle_state: str = Lifecycle.IN_USE, receipt_ref: str = "",
                       condition: str | None = None) -> list[int]:
        """Record the accepted part of a delivery once (BR-07).

        Updates departmental allocation, responsible custodian and location
        of the accepted units only. KU legal ownership is unchanged (BR-03).
        """
        _require_transaction()
        if lifecycle_state not in RECEIPT_STATES:
            raise ValidationFailed("Accepted units become In use or Available.")
        payload = {"consignment": consignment_ref, "quantity": str(quantity), "receipt": receipt_ref}
        if (replayed := cls._replay(actor, "receive", payload)) is not None:
            return replayed["portions"]
        rows = cls._transit_rows(consignment_ref)
        if not rows:
            raise StockConflict("Nothing from this consignment is still in transit.")
        qty = _quantity(quantity, rows[0].asset.unit)
        if qty > sum((p.quantity for p in rows), ZERO):
            raise StockConflict("Cannot accept more than the quantity in transit.")
        changes = {
            "lifecycle_state": lifecycle_state,
            "allocation": Allocation.FREE,
            "claim_ref": "",
            "department_id": getattr(department, "pk", department),
            "location_id": getattr(location, "pk", location),
            "custodian_id": getattr(custodian, "pk", custodian),
            "temporary_custodian_id": None,
        }
        if condition:
            changes["condition"] = condition
        accepted = cls._take(rows, qty, **changes)
        result = {"portions": [p.pk for p in accepted]}
        for index, part in enumerate(accepted):
            cls._event(actor, "receive", payload, portion=part, event_type=AssetEventType.RECEIVED,
                       quantity=part.quantity, reference=receipt_ref or consignment_ref,
                       details={"consignment": consignment_ref, "department": changes["department_id"],
                                "location": changes["location_id"], "custodian": changes["custodian_id"]},
                       result=result if index == 0 else None)
        cls._sync_individual_asset(accepted)
        return result["portions"]

    @classmethod
    def record_return(cls, actor: ActorContext, *, consignment_ref: str, quantity, location,
                      reference: str = "") -> list[int]:
        """Actual physical return: units go to inspection before any new release."""
        _require_transaction()
        payload = {"consignment": consignment_ref, "quantity": str(quantity), "ref": reference}
        if (replayed := cls._replay(actor, "return", payload)) is not None:
            return replayed["portions"]
        rows = cls._transit_rows(consignment_ref)
        if not rows:
            raise StockConflict("Nothing from this consignment is still in transit.")
        qty = _quantity(quantity, rows[0].asset.unit)
        if qty > sum((p.quantity for p in rows), ZERO):
            raise StockConflict("Cannot return more than the quantity in transit.")
        parts = cls._take(rows, qty, lifecycle_state=Lifecycle.UNDER_INSPECTION, allocation=Allocation.FREE,
                          claim_ref="", listing_ref=None, temporary_custodian_id=None,
                          location_id=getattr(location, "pk", location))
        result = {"portions": [p.pk for p in parts]}
        for index, part in enumerate(parts):
            cls._event(actor, "return", payload, portion=part, event_type=AssetEventType.RETURNED,
                       quantity=part.quantity, reference=reference or consignment_ref,
                       result=result if index == 0 else None)
        return result["portions"]

    @classmethod
    def record_lost(cls, actor: ActorContext, *, consignment_ref: str, quantity, reference: str) -> list[int]:
        """Authorised loss. A lost unit never becomes available again."""
        _require_transaction()
        payload = {"consignment": consignment_ref, "quantity": str(quantity), "ref": reference}
        if (replayed := cls._replay(actor, "lost", payload)) is not None:
            return replayed["portions"]
        rows = cls._transit_rows(consignment_ref)
        if not rows:
            raise StockConflict("Nothing from this consignment is still in transit.")
        qty = _quantity(quantity, rows[0].asset.unit)
        if qty > sum((p.quantity for p in rows), ZERO):
            raise StockConflict("Cannot record more lost units than are in transit.")
        parts = cls._take(rows, qty, lifecycle_state=Lifecycle.LOST, allocation=Allocation.SETTLED)
        result = {"portions": [p.pk for p in parts]}
        for index, part in enumerate(parts):
            cls._event(actor, "lost", payload, portion=part, event_type=AssetEventType.LOST, quantity=part.quantity,
                       reference=reference, result=result if index == 0 else None)
        return result["portions"]

    @classmethod
    def _take(cls, rows: list[AssetPortion], qty: Decimal, **changes) -> list[AssetPortion]:
        remaining = qty
        parts = []
        for portion in rows:
            if remaining <= ZERO:
                break
            take = min(remaining, portion.quantity)
            parts.append(cls._split_locked(portion, take, **changes))
            remaining -= take
        return parts

    @staticmethod
    def _sync_individual_asset(portions: list[AssetPortion]) -> None:
        """When every current unit of an asset sits with one holder, the asset
        record's responsible department/custodian/location follow it."""
        from inventory.models import Asset

        for asset_id in {p.asset_id for p in portions}:
            current = AssetPortion.objects.filter(asset_id=asset_id, is_active_leaf=True, quantity__gt=0).exclude(
                lifecycle_state__in=Lifecycle.final_states()
            )
            holders = set(current.values_list("department_id", "custodian_id", "location_id"))
            if len(holders) == 1:
                dept, custodian, location = holders.pop()
                Asset.objects.filter(pk=asset_id).update(
                    department_id=dept, custodian_id=custodian, location_id=location, version=F("version") + 1
                )

    # ------------------------------------------------------------------
    # Lifecycle, condition and safety (consumed by care and final actions)
    # ------------------------------------------------------------------
    @classmethod
    def change_lifecycle(cls, actor: ActorContext, portion_id: int, to_state: str, *, quantity=None,
                         reference: str = "", reason: str = "", expected_version=None) -> AssetPortion:
        _require_transaction()
        payload = {"portion": portion_id, "to": to_state, "quantity": str(quantity)}
        if (replayed := cls._replay(actor, "lifecycle", payload)) is not None:
            return AssetPortion.objects.get(pk=replayed["portion"])
        (portion,) = cls._lock([portion_id])
        cls._check_version(portion, expected_version)
        if not portion.is_active_leaf:
            raise StockConflict("This portion is no longer current.")
        allowed = LIFECYCLE_TRANSITIONS.get(portion.lifecycle_state, set())
        if to_state not in allowed:
            raise ValidationFailed(
                f"{portion.get_lifecycle_state_display()} cannot change to {Lifecycle(to_state).label} here."
            )
        if portion.allocation != Allocation.FREE and to_state not in CLAIMED_TRANSITIONS:
            raise StockConflict("Units with an active claim can only be sent for inspection.")
        qty = portion.quantity if quantity is None else _quantity(quantity, portion.asset.unit)
        before = portion.lifecycle_state
        part = cls._split_locked(portion, qty, lifecycle_state=to_state)
        cls._event(actor, "lifecycle", payload, portion=part, event_type=AssetEventType.LIFECYCLE_CHANGED,
                   quantity=qty, reference=reference, details={"from": before, "to": to_state, "reason": reason},
                   result={"portion": part.pk})
        return part

    @classmethod
    def record_condition(cls, actor: ActorContext, portion_id: int, condition: str, *, quantity=None,
                         reference: str = "", evidence_refs=None) -> AssetPortion:
        _require_transaction()
        payload = {"portion": portion_id, "condition": condition, "quantity": str(quantity)}
        if (replayed := cls._replay(actor, "condition", payload)) is not None:
            return AssetPortion.objects.get(pk=replayed["portion"])
        (portion,) = cls._lock([portion_id])
        if not portion.is_active_leaf or portion.lifecycle_state in Lifecycle.final_states():
            raise StockConflict("Condition cannot change on this portion.")
        if portion.allocation != Allocation.FREE and quantity is not None and _quantity(
                quantity, portion.asset.unit) != portion.quantity:
            raise StockConflict("Claimed units are updated as a whole.")
        qty = portion.quantity if quantity is None else _quantity(quantity, portion.asset.unit)
        before = portion.condition
        part = cls._split_locked(portion, qty, condition=condition)
        cls._event(actor, "condition", payload, portion=part, event_type=AssetEventType.CONDITION_RECORDED,
                   quantity=qty, reference=reference, evidence_refs=evidence_refs,
                   details={"from": before, "to": condition}, result={"portion": part.pk})
        return part

    @classmethod
    def record_safety(cls, actor: ActorContext, portion_id: int, safety_state: str, *, evidence_ref: str,
                      quantity=None, reference: str = "") -> AssetPortion:
        """Record a qualified reviewer's safety decision.

        The caller (Sinan's CareService) checks the reviewer's authority. A
        restriction applies immediately, even to claimed units; it overlays
        the claim for review rather than releasing it (NFR-07).
        """
        _require_transaction()
        if not evidence_ref:
            raise ValidationFailed("A safety decision needs supporting evidence.")
        payload = {"portion": portion_id, "safety": safety_state, "quantity": str(quantity), "evidence": evidence_ref}
        if (replayed := cls._replay(actor, "safety", payload)) is not None:
            return AssetPortion.objects.get(pk=replayed["portion"])
        (portion,) = cls._lock([portion_id])
        if not portion.is_active_leaf or portion.lifecycle_state in Lifecycle.final_states():
            raise StockConflict("Safety cannot change on this portion.")
        qty = portion.quantity if quantity is None else _quantity(quantity, portion.asset.unit)
        if portion.allocation != Allocation.FREE and qty != portion.quantity:
            raise StockConflict("Claimed units are updated as a whole.")
        before = portion.safety_state
        part = cls._split_locked(portion, qty, safety_state=safety_state, safety_evidence_ref=evidence_ref)
        cls._event(actor, "safety", payload, portion=part, event_type=AssetEventType.SAFETY_RECORDED, quantity=qty,
                   reference=reference, evidence_refs=[evidence_ref],
                   details={"from": before, "to": safety_state, "claim": part.claim_ref},
                   result={"portion": part.pk})
        return part

    @classmethod
    def execute_final(cls, actor: ActorContext, *, claim_ref: str, quantity, outcome: str, reference: str,
                      evidence_refs=None) -> list[int]:
        """Apply a final outcome once, for the executed quantity only (BR-12)."""
        _require_transaction()
        if outcome not in FINAL_OUTCOMES:
            raise ValidationFailed("Unknown final outcome.")
        if not evidence_refs:
            raise ValidationFailed("Final execution needs physical evidence (receipt or certificate).")
        payload = {"claim": claim_ref, "quantity": str(quantity), "outcome": outcome, "ref": reference}
        if (replayed := cls._replay(actor, "final", payload)) is not None:
            return replayed["portions"]
        ids = list(AssetPortion.objects.filter(claim_ref=claim_ref, is_active_leaf=True).values_list("pk", flat=True))
        rows = [p for p in cls._lock(ids) if p.allocation == Allocation.FINAL_COMMITTED]
        if not rows:
            raise StockConflict("There are no units committed to this final action.")
        qty = _quantity(quantity, rows[0].asset.unit)
        if qty > sum((p.quantity for p in rows), ZERO):
            raise StockConflict("Cannot execute more than the committed quantity.")
        parts = cls._take(rows, qty, lifecycle_state=outcome, allocation=Allocation.SETTLED)
        result = {"portions": [p.pk for p in parts]}
        for index, part in enumerate(parts):
            cls._event(actor, "final", payload, portion=part, event_type=AssetEventType.FINAL_EXECUTED,
                       quantity=part.quantity, reference=reference, evidence_refs=evidence_refs,
                       details={"outcome": outcome}, result=result if index == 0 else None)
        return result["portions"]

    # ------------------------------------------------------------------
    # Integrity checks (used by tests, restore checks and monitoring)
    # ------------------------------------------------------------------
    @staticmethod
    def expected_total(asset) -> Decimal:
        adjustments = (
            AssetEvent.objects.filter(asset=asset, event_type=AssetEventType.ADJUSTED).aggregate(s=Sum("quantity"))["s"]
            or ZERO
        )
        return asset.registered_quantity + adjustments

    @classmethod
    def verify_conservation(cls, asset) -> tuple[bool, Decimal, Decimal]:
        actual = (
            AssetPortion.objects.filter(asset=asset, is_active_leaf=True).aggregate(s=Sum("quantity"))["s"] or ZERO
        )
        expected = cls.expected_total(asset)
        return actual == expected, expected, actual


def run_atomic(fn, *args, **kwargs):
    """Helper for callers that do not already hold a transaction."""
    with transaction.atomic():
        return fn(*args, **kwargs)
