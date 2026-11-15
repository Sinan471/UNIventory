from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from catalogue.tests import publish
from core.contracts import NotPermitted, ValidationFailed
from core.testing import World, batch, user
from demand.services import DemandService
from identity.models import Role
from inventory.models import Allocation, AssetPortion
from workflow.services import ApprovalService
from .models import Reservation
from .services import ReservationService, TransferService
from jobs.models import WorkItem
from jobs.services import WorkDispatcher


class TransferTests(TestCase):
    def setUp(self):
        self.w = World()
        self.dest_rep = user("destrep", (Role.DEPT_REP, self.w.other))
        self.receiver = user("receiver", (Role.RECEIVER, self.w.other))
        asset = batch(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, quantity=4)
        self.listing = publish(self.w, asset)
        self.need = DemandService.save(self.w.requester, {"department": self.w.other, "title": "Chairs", "purpose": "Room",
            "specifications": "", "quantity": Decimal("3"), "needed_by": None, "urgent": False, "urgent_reason": ""}, submit=True)
        ApprovalService.decide_request(self.dest_rep, self.need.pk, self.need.version, "approve")

    def test_hold_commit_partial_receipt_and_replay(self):
        reservation = ReservationService.request(self.w.requester, self.need.pk, self.listing.pk, 3)
        self.assertFalse(AssetPortion.objects.filter(claim_ref=reservation.claim_ref, allocation=Allocation.HELD).exists())
        reservation = ReservationService.approve(self.w.rep, reservation.pk, 1)
        reservation = ReservationService.commit(self.dest_rep, reservation.pk, 2)
        shipment = TransferService.dispatch(self.w.custodian, reservation.pk, 3, self.receiver, self.w.other_loc, self.w.other_custodian, "dispatch-key")
        replay = TransferService.dispatch(self.w.custodian, reservation.pk, 3, self.receiver, self.w.other_loc, self.w.other_custodian, "dispatch-key")
        self.assertEqual(shipment.pk, replay.pk)
        with self.assertRaises(NotPermitted):
            TransferService.receive(self.w.requester, shipment.pk, 1, "receipt-key")
        first = TransferService.receive(self.receiver, shipment.pk, 1, "receipt-key")
        replay = TransferService.receive(self.receiver, shipment.pk, 1, "receipt-key")
        self.assertEqual(first.pk, replay.pk)
        self.assertEqual(shipment.receipts.count(), 1)
        with self.assertRaises(ValidationFailed):
            TransferService.receive(self.receiver, shipment.pk, 2, "receipt-key")
        self.need.refresh_from_db()
        self.assertEqual(self.need.outstanding_quantity, Decimal("2"))
        TransferService.resolve(self.w.custodian, shipment.pk, 1, "RETURNED", "Damaged in transit", self.w.loc)
        TransferService.resolve(self.w.rep, shipment.pk, 1, "LOST", "Not located")
        self.need.refresh_from_db()
        self.assertEqual(self.need.outstanding_quantity, Decimal("2"))

    def test_expired_hold_releases_stock(self):
        reservation = ReservationService.request(self.w.requester, self.need.pk, self.listing.pk, 2)
        reservation = ReservationService.approve(self.w.rep, reservation.pk, 1)
        Reservation.objects.filter(pk=reservation.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        job = WorkItem.objects.get(kind="expire_hold", object_id=reservation.pk)
        WorkItem.objects.filter(pk=job.pk).update(due_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(WorkDispatcher.run_one(job.pk))
        self.assertFalse(WorkDispatcher.run_one(job.pk))
        reservation.refresh_from_db()
        self.assertEqual(reservation.state, Reservation.State.EXPIRED)
        self.assertFalse(AssetPortion.objects.filter(claim_ref=reservation.claim_ref, allocation=Allocation.HELD).exists())

    def test_reservation_pages_enforce_scope(self):
        reservation = ReservationService.request(self.w.requester, self.need.pk, self.listing.pk, 2)
        self.client.force_login(self.w.requester)
        self.assertEqual(self.client.get(reverse("transfer:detail", args=[reservation.pk])).status_code, 200)
        self.client.force_login(self.w.other_custodian)
        self.assertEqual(self.client.get(reverse("transfer:detail", args=[reservation.pk])).status_code, 404)
        self.client.force_login(self.w.rep)
        self.assertEqual(self.client.get(reverse("transfer:detail", args=[reservation.pk])).status_code, 200)
