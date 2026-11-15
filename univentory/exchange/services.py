from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from catalogue.services import CatalogueQueryService, CatalogueService
from core.contracts import ActorContext, NotPermitted, StaleVersion, ValidationFailed
from core.contracts.audit import audit
from demand.models import ResourceRequest
from identity.models import Role
from identity.policy import AccessPolicy
from inventory.ledger import InventoryLedger
from .models import Consignment, DiscrepancyResolution, ReceiptEvent, Reservation


class ReservationService:
    @staticmethod
    @transaction.atomic
    def request(user, request_id, listing_id, quantity):
        need = ResourceRequest.objects.select_for_update().get(pk=request_id, requester=user)
        if not AccessPolicy.has_role(user, Role.REQUESTER, need.department):
            raise NotPermitted("Your requester access is no longer active.")
        if need.state not in (ResourceRequest.State.APPROVED, ResourceRequest.State.PARTIAL):
            raise ValidationFailed("The need must be approved first.")
        listing = CatalogueQueryService.get_visible(user, listing_id)
        qty = Decimal(str(quantity))
        if qty <= 0 or qty > need.quantity:
            raise ValidationFailed("Enter a positive quantity no greater than the request.")
        row = Reservation.objects.create(request=need, listing=listing, quantity=qty, requested_by=user)
        audit("reservation.request", row, user, after={"quantity": str(qty), "state": row.state})
        return row

    @staticmethod
    @transaction.atomic
    def approve(user, reservation_id, expected_version):
        row = Reservation.objects.select_for_update().select_related("listing", "request").get(pk=reservation_id)
        if not AccessPolicy.has_role(user, Role.DEPT_REP, row.listing.department_id) or user.pk == row.requested_by_id:
            raise NotPermitted("An independent source department representative must approve the hold.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != Reservation.State.PENDING or row.request.state not in (ResourceRequest.State.APPROVED, ResourceRequest.State.PARTIAL):
            raise ValidationFailed("This reservation is no longer awaiting review.")
        need = ResourceRequest.objects.select_for_update().get(pk=row.request_id)
        allocated = Reservation.objects.filter(request=need, state__in=[Reservation.State.HELD, Reservation.State.COMMITTED]).aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        resolved = DiscrepancyResolution.objects.filter(consignment__reservation__request=need,
            consignment__reservation__state=Reservation.State.COMMITTED).aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        allocated -= resolved
        if allocated + row.quantity > need.quantity:
            raise ValidationFailed("This hold exceeds the remaining quantity of the approved need.")
        actor = ActorContext(user, operation_key=f"hold:{row.pk}:{row.version}")
        CatalogueService.hold(actor, listing_id=row.listing_id, quantity=row.quantity, claim_ref=row.claim_ref)
        row.state, row.approved_by, row.expires_at = Reservation.State.HELD, user, timezone.now() + timedelta(hours=48)
        row.version += 1
        row.save(update_fields=["state", "approved_by", "expires_at", "version"])
        from jobs.services import WorkDispatcher
        WorkDispatcher.schedule_hold_expiry(row)
        audit("reservation.held", row, actor, after={"quantity": str(row.quantity), "expires_at": row.expires_at.isoformat()})
        return row

    @staticmethod
    @transaction.atomic
    def commit(user, reservation_id, expected_version):
        row = Reservation.objects.select_for_update().select_related("listing", "request").get(pk=reservation_id)
        if not AccessPolicy.has_role(user, Role.DEPT_REP, row.request.department_id) or user.pk == row.requested_by_id:
            raise NotPermitted("An independent destination department representative must approve the transfer.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != Reservation.State.HELD or row.expires_at <= timezone.now():
            raise ValidationFailed("The hold is not active or has expired.")
        actor = ActorContext(user, operation_key=f"commit:{row.pk}:{row.version}")
        InventoryLedger.commit(actor, claim_ref=row.claim_ref)
        row.state = Reservation.State.COMMITTED
        row.version += 1
        row.save(update_fields=["state", "version"])
        audit("transfer.approve", row, actor, after={"state": row.state})
        return row

    @staticmethod
    @transaction.atomic
    def expire(user, reservation_id):
        row = Reservation.objects.select_for_update().get(pk=reservation_id)
        if row.state != Reservation.State.HELD or row.expires_at > timezone.now():
            return False
        actor = ActorContext(user, operation_key=f"expire:{row.pk}")
        InventoryLedger.release_claim(actor, claim_ref=row.claim_ref, reason="Hold expired")
        row.state = Reservation.State.EXPIRED
        row.version += 1
        row.save(update_fields=["state", "version"])
        audit("reservation.expire", row, actor, after={"state": row.state})
        return True

    @staticmethod
    @transaction.atomic
    def reject(user, reservation_id, expected_version, reason):
        row = Reservation.objects.select_for_update().select_related("listing").get(pk=reservation_id)
        if not AccessPolicy.has_role(user, Role.DEPT_REP, row.listing.department_id) or user.pk == row.requested_by_id:
            raise NotPermitted("An independent source department representative must review this reservation.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != Reservation.State.PENDING or not reason.strip():
            raise ValidationFailed("A pending reservation and a reason are required.")
        row.state, row.version, row.state_reason = Reservation.State.REJECTED, row.version + 1, reason.strip()
        row.save(update_fields=["state", "version", "state_reason"])
        audit("reservation.reject", row, user, after={"state": row.state}, reason=reason)
        from notifications.services import NotificationService
        NotificationService.notify(row.requested_by, "A reservation was rejected. Open reservations and transfers for details.")
        return row

    @staticmethod
    @transaction.atomic
    def cancel(user, reservation_id, expected_version, reason):
        row = Reservation.objects.select_for_update().select_related("request").get(pk=reservation_id)
        if user.pk != row.requested_by_id or not AccessPolicy.has_role(user, Role.REQUESTER, row.request.department_id):
            raise NotPermitted("Only the requester can cancel this reservation.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state not in (Reservation.State.PENDING, Reservation.State.HELD, Reservation.State.COMMITTED) or not reason.strip():
            raise ValidationFailed("An active reservation and a reason are required.")
        if row.state == Reservation.State.COMMITTED and row.consignments.exists():
            raise ValidationFailed("Dispatched quantities must be resolved before this reservation can be cancelled.")
        actor = ActorContext(user, operation_key=f"cancel-reservation:{row.pk}:{row.version}")
        if row.state in (Reservation.State.HELD, Reservation.State.COMMITTED):
            InventoryLedger.release_claim(actor, claim_ref=row.claim_ref, reason=reason.strip())
        row.state, row.version, row.state_reason = Reservation.State.RELEASED, row.version + 1, reason.strip()
        row.save(update_fields=["state", "version", "state_reason"])
        audit("reservation.cancel", row, actor, after={"state": row.state}, reason=reason)
        return row


class TransferService:
    @staticmethod
    @transaction.atomic
    def dispatch(user, reservation_id, quantity, receiver, destination, custodian, operation_key):
        row = Reservation.objects.select_for_update().select_related("listing__asset", "request").get(pk=reservation_id)
        if not AccessPolicy.can_edit_asset(user, row.listing.asset):
            raise NotPermitted("Only the assigned source custodian can dispatch.")
        if not operation_key or len(operation_key) > 64:
            raise ValidationFailed("A valid dispatch operation key is required.")
        qty = Decimal(str(quantity))
        previous = Consignment.objects.filter(operation_key=operation_key).first()
        if previous:
            if (previous.reservation_id != row.pk or previous.dispatched_by_id != user.pk or previous.quantity != qty
                    or previous.receiver_id != receiver.pk or previous.destination_id != destination.pk or previous.custodian_id != custodian.pk):
                raise ValidationFailed("This dispatch key was already used for different details.")
            return previous
        if row.state != Reservation.State.COMMITTED:
            raise ValidationFailed("The transfer must be approved before dispatch.")
        if destination.department_id != row.request.department_id or not destination.is_active:
            raise ValidationFailed("The destination must be an active location in the requesting department.")
        if not AccessPolicy.has_role(receiver, Role.RECEIVER, row.request.department_id):
            raise ValidationFailed("Choose an active receiver for the destination department.")
        if not AccessPolicy.has_role(custodian, Role.CUSTODIAN, row.request.department_id):
            raise ValidationFailed("Choose an active custodian for the destination department.")
        sent = row.consignments.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        if qty <= 0 or qty + sent > row.quantity:
            raise ValidationFailed("The dispatch quantity exceeds the approved quantity.")
        consignment = Consignment.objects.create(reservation=row, quantity=qty, receiver=receiver, destination=destination,
                                                 custodian=custodian, dispatched_by=user, operation_key=operation_key)
        actor = ActorContext(user, operation_key=f"dispatch:{consignment.pk}")
        InventoryLedger.dispatch(actor, claim_ref=row.claim_ref, quantity=qty, consignment_ref=consignment.reference, temporary_custodian=user)
        audit("transfer.dispatch", consignment, actor, after={"quantity": str(qty)})
        return consignment

    @staticmethod
    @transaction.atomic
    def receive(user, consignment_id, quantity, operation_key):
        if not operation_key or len(operation_key) > 64:
            raise ValidationFailed("A receipt operation key is required.")
        consignment = Consignment.objects.select_for_update().select_related("reservation__request", "destination", "custodian").get(pk=consignment_id)
        need = ResourceRequest.objects.select_for_update().get(pk=consignment.reservation.request_id)
        if consignment.receiver_id != user.pk or not AccessPolicy.has_role(user, Role.RECEIVER, need.department_id):
            raise NotPermitted("Only the assigned receiver can confirm this receipt.")
        qty = Decimal(str(quantity))
        previous = ReceiptEvent.objects.filter(operation_key=operation_key).first()
        if previous:
            if previous.consignment_id != consignment.pk or previous.actor_id != user.pk or previous.quantity != qty:
                raise ValidationFailed("This receipt key was already used for different details.")
            return previous
        received = consignment.receipts.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        resolved = consignment.resolutions.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        if qty <= 0 or received + resolved + qty > consignment.quantity:
            raise ValidationFailed("The receipt exceeds the quantity dispatched.")
        actor = ActorContext(user, operation_key=operation_key)
        InventoryLedger.accept_receipt(actor, consignment_ref=consignment.reference, quantity=qty,
            department=need.department, location=consignment.destination, custodian=consignment.custodian,
            receipt_ref=f"receipt:{operation_key}")
        receipt = ReceiptEvent.objects.create(consignment=consignment, actor=user, quantity=qty, operation_key=operation_key)
        accepted = need.accepted_quantity
        need.state = ResourceRequest.State.FULFILLED if accepted >= need.quantity else ResourceRequest.State.PARTIAL
        need.version += 1
        need.save(update_fields=["state", "version", "updated_at"])
        from demand.models import RequestEvent
        RequestEvent.objects.create(request=need, actor=user, action="Receipt accepted")
        audit("transfer.receive", receipt, actor, after={"quantity": str(qty)})
        from notifications.services import NotificationService
        NotificationService.notify(need.requester, "A receipt was recorded for one of your requests. Open My Requests for details.")
        return receipt

    @staticmethod
    @transaction.atomic
    def resolve(user, consignment_id, quantity, kind, reason, location=None):
        shipment = Consignment.objects.select_for_update().select_related("reservation__listing__asset", "reservation__listing").get(pk=consignment_id)
        listing = shipment.reservation.listing
        if kind == "RETURNED":
            if not AccessPolicy.can_edit_asset(user, listing.asset):
                raise NotPermitted("The source custodian must record a physical return.")
            if location is None or location.department_id != listing.department_id or not location.is_active:
                raise ValidationFailed("Choose an active source department location.")
        elif kind == "LOST":
            if not AccessPolicy.has_role(user, Role.DEPT_REP, listing.department_id):
                raise NotPermitted("A source department representative must record a loss.")
        else:
            raise ValidationFailed("Choose a valid resolution.")
        if not reason.strip():
            raise ValidationFailed("Give a reason for the resolution.")
        qty = Decimal(str(quantity))
        received = shipment.receipts.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        resolved = shipment.resolutions.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        if qty <= 0 or received + resolved + qty > shipment.quantity:
            raise ValidationFailed("The resolution exceeds the unresolved quantity.")
        row = DiscrepancyResolution.objects.create(consignment=shipment, actor=user, quantity=qty, kind=kind, reason=reason.strip())
        actor = ActorContext(user, operation_key=f"resolution:{row.pk}")
        if kind == "RETURNED":
            InventoryLedger.record_return(actor, consignment_ref=shipment.reference, quantity=qty, location=location, reference=f"resolution:{row.pk}")
        else:
            InventoryLedger.record_lost(actor, consignment_ref=shipment.reference, quantity=qty, reference=f"resolution:{row.pk}")
        audit("transfer.resolution", row, actor, after={"kind": kind, "quantity": str(qty)}, reason=reason)
        return row
