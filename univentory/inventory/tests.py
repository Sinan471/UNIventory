"""Asset records, ledger integrity and evidence tests (FR-05..FR-10, NFR-04, NFR-11, NFR-15)."""
import io
import threading
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone

from core.contracts import (
    DuplicateOperationConflict,
    NotPermitted,
    StaleVersion,
    StockConflict,
    ValidationFailed,
)
from core.testing import World, actor, asset_input, batch, register
from identity.tests import sign_in
from inventory.ledger import InventoryLedger
from inventory.models import (
    Allocation,
    AssetEvent,
    AssetEventType,
    AssetPortion,
    AttachmentAccess,
    Lifecycle,
    SafetyState,
    TrackingType,
)
from inventory.services import AttachmentService, InventoryService


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 108, 96)).save(buf, format="PNG")
    return buf.getvalue()


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class AssetRecordTests(TestCase):
    def setUp(self):
        self.w = World()

    def test_register_retains_every_field_and_assigns_id(self):
        asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, material="Aluminium",
                         tags=["Laptop", "laptop", " teaching "])
        self.assertRegex(asset.asset_code, r"^KU-\d{4}-\d{6}$")
        self.assertEqual(asset.legal_owner, "Khalifa University")
        self.assertEqual(asset.tags, ["laptop", "teaching"])
        self.assertEqual(asset.specifications, {"ram_gb": 16})
        self.assertEqual(asset.events.filter(event_type=AssetEventType.REGISTERED).count(), 1)

    def test_missing_history_must_be_explicitly_unknown(self):
        with self.assertRaises(ValidationFailed) as ctx:
            InventoryService.register(actor(self.w.custodian), asset_input(
                self.w.dept, self.w.loc, self.w.cat, acquisition_date=None, estimated_value_aed=None))
        self.assertIn("acquisition_date", ctx.exception.field_errors)
        self.assertIn("estimated_value_aed", ctx.exception.field_errors)
        asset = InventoryService.register(actor(self.w.custodian), asset_input(
            self.w.dept, self.w.loc, self.w.cat, acquisition_date=None, acquisition_date_unknown=True,
            estimated_value_aed=None, estimated_value_unknown=True))
        self.assertIsNone(asset.acquisition_date)
        self.assertTrue(asset.acquisition_date_unknown)

    def test_invalid_values_rejected_with_field(self):
        cases = [
            ({"estimated_value_aed": Decimal("-1")}, "estimated_value_aed"),
            ({"acquisition_date": timezone.localdate() + timedelta(days=3)}, "acquisition_date"),
            ({"quantity": Decimal("2")}, "quantity"),  # individual item must be 1
            ({"specifications": {"ram_gb": "lots"}}, "spec_ram_gb"),
            ({"specifications": {"colour": "red"}}, "specifications"),
            ({"ownership_restriction": "LEASED"}, "restriction_notes"),
            ({"is_data_bearing": True}, "handling_notes"),
        ]
        for overrides, field in cases:
            with self.subTest(field=field), self.assertRaises(ValidationFailed) as ctx:
                InventoryService.register(actor(self.w.custodian), asset_input(self.w.dept, self.w.loc, self.w.cat,
                                                                               **overrides))
            self.assertIn(field, ctx.exception.field_errors)

    def test_batch_counted_units_must_be_whole(self):
        with self.assertRaises(ValidationFailed):
            batch(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, quantity=Decimal("2.5"))

    def test_only_department_custodian_registers(self):
        with self.assertRaises(NotPermitted):
            InventoryService.register(actor(self.w.requester), asset_input(self.w.dept, self.w.loc, self.w.cat))
        with self.assertRaises(NotPermitted):
            InventoryService.register(actor(self.w.other_custodian), asset_input(self.w.dept, self.w.loc, self.w.cat))

    def test_repeated_registration_submission_is_applied_once(self):
        a1 = InventoryService.register(actor(self.w.custodian, "form-1"), asset_input(self.w.dept, self.w.loc, self.w.cat))
        a2 = InventoryService.register(actor(self.w.custodian, "form-1"), asset_input(self.w.dept, self.w.loc, self.w.cat))
        self.assertEqual(a1.pk, a2.pk)

    def test_edit_only_assigned_and_stale_edit_conflicts(self):
        asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        with self.assertRaises(NotPermitted):
            InventoryService.update(actor(self.w.custodian2), asset.pk, {"title": "X"}, expected_version=asset.version)
        InventoryService.update(actor(self.w.custodian), asset.pk, {"title": "Updated"}, expected_version=asset.version)
        with self.assertRaises(StaleVersion):
            InventoryService.update(actor(self.w.custodian), asset.pk, {"title": "Overwrite"},
                                    expected_version=asset.version)
        asset.refresh_from_db()
        self.assertEqual(asset.title, "Updated")
        event = asset.events.filter(event_type=AssetEventType.UPDATED).get()
        self.assertEqual(event.details["after"]["title"], "Updated")

    def test_events_are_immutable_and_assets_not_deletable(self):
        asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        event = asset.events.first()
        event.details = {"tampered": True}
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            AssetEvent.objects.filter(pk=event.pk).update(details={})
        with self.assertRaises(ValidationError):
            asset.delete()

    def test_edit_page_shows_stale_warning(self):
        asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        client = Client()
        sign_in(client, self.w.custodian)
        data = {"version": asset.version - 1, "title": "New", "description": "d", "category": self.w.cat.pk,
                "location": self.w.loc.pk, "legal_owner": "Khalifa University", "acquisition_date": "2022-01-10",
                "estimated_value_aed": "10", "ownership_restriction": "NONE", "provenance": "OPERATIONAL"}
        response = client.post(f"/inventory/{asset.pk}/edit/", data)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Someone else changed this record", status_code=409)

    def test_invalid_form_preserves_values(self):
        client = Client()
        sign_in(client, self.w.custodian)
        response = client.post("/inventory/new/", {
            "title": "Microscope", "description": "Teaching scope", "category": self.w.cat.pk,
            "tracking_type": "BATCH", "quantity": "-3", "unit": "EA", "condition": "GOOD",
            "department": self.w.dept.pk, "location": self.w.loc.pk, "legal_owner": "Khalifa University",
            "acquisition_date_unknown": "on", "estimated_value_unknown": "on", "ownership_restriction": "NONE",
            "provenance": "OPERATIONAL",
        })
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'value="Microscope"', status_code=422)


class LedgerTests(TestCase):
    def setUp(self):
        self.w = World()
        self.chairs = batch(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, quantity=10)
        self.root = self.chairs.portions.get()

    def assertConserved(self, asset=None):
        ok, expected, actual = InventoryLedger.verify_conservation(asset or self.chairs)
        self.assertTrue(ok, f"expected {expected}, found {actual}")

    def test_split_conserves_quantity_and_links_records(self):
        _, child = InventoryService.split_batch(actor(self.w.custodian), self.root.pk, 4,
                                                expected_version=self.root.version)
        self.root.refresh_from_db()
        self.assertEqual((self.root.quantity, child.quantity), (Decimal(6), Decimal(4)))
        self.assertEqual(child.parent_id, self.root.pk)
        self.assertTrue(child.path.startswith(self.root.path))
        self.assertConserved()

    def test_split_rejects_stale_version_and_full_quantity(self):
        with self.assertRaises(StaleVersion):
            InventoryService.split_batch(actor(self.w.custodian), self.root.pk, 2, expected_version=99)
        with self.assertRaises(ValidationFailed):
            InventoryService.split_batch(actor(self.w.custodian), self.root.pk, 10, expected_version=self.root.version)

    def test_individual_items_cannot_be_split(self):
        laptop = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        portion = laptop.portions.get()
        with self.assertRaises(ValidationFailed):
            InventoryService.split_batch(actor(self.w.custodian), portion.pk, 1, expected_version=portion.version)

    def test_documented_ten_chair_example(self):
        """Phase 3, 6.2.5: hold 4, commit, dispatch, accept 3, dispute 1."""
        a = actor(self.w.custodian)
        with transaction.atomic():
            InventoryLedger.claim(a, candidate_portion_ids=[self.root.pk], quantity=4, claim_ref="reservation:1")
        free = AssetPortion.objects.filter(asset=self.chairs, allocation=Allocation.FREE).get()
        self.assertEqual(free.quantity, 6)
        with transaction.atomic():
            InventoryLedger.commit(a, claim_ref="reservation:1")
            InventoryLedger.dispatch(a, claim_ref="reservation:1", quantity=4, consignment_ref="consignment:1",
                                     temporary_custodian=self.w.custodian2)
        with transaction.atomic():
            InventoryLedger.accept_receipt(a, consignment_ref="consignment:1", quantity=3, department=self.w.other,
                                           location=self.w.other_loc, custodian=self.w.other_custodian,
                                           receipt_ref="receipt:1")
        current = AssetPortion.objects.filter(asset=self.chairs, is_active_leaf=True)
        at_source = sum(p.quantity for p in current if p.department_id == self.w.dept.pk
                        and p.lifecycle_state != Lifecycle.IN_TRANSIT)
        at_dest = sum(p.quantity for p in current if p.department_id == self.w.other.pk)
        in_review = sum(p.quantity for p in current if p.lifecycle_state == Lifecycle.IN_TRANSIT)
        self.assertEqual((at_source, at_dest, in_review), (6, 3, 1))
        self.chairs.refresh_from_db()
        self.assertEqual(self.chairs.legal_owner, "Khalifa University")  # BR-03
        self.assertEqual(self.chairs.department_id, self.w.dept.pk)  # batch split across departments
        self.assertConserved()

    def test_receipt_replay_applies_once_and_key_reuse_rejected(self):
        a = actor(self.w.custodian)
        with transaction.atomic():
            InventoryLedger.claim(a, candidate_portion_ids=[self.root.pk], quantity=2, claim_ref="r:2")
            InventoryLedger.commit(a, claim_ref="r:2")
            InventoryLedger.dispatch(a, claim_ref="r:2", quantity=2, consignment_ref="c:2",
                                     temporary_custodian=self.w.custodian2)
        keyed = actor(self.w.other_custodian, "receipt-key-1")
        for _ in range(2):
            with transaction.atomic():
                InventoryLedger.accept_receipt(keyed, consignment_ref="c:2", quantity=2, department=self.w.other,
                                               location=self.w.other_loc, custodian=self.w.other_custodian)
        self.assertEqual(AssetEvent.objects.filter(event_type=AssetEventType.RECEIVED).count(), 1)
        with self.assertRaises(DuplicateOperationConflict), transaction.atomic():
            InventoryLedger.accept_receipt(keyed, consignment_ref="c:2", quantity=1, department=self.w.other,
                                           location=self.w.other_loc, custodian=self.w.other_custodian)
        self.assertConserved()

    def test_individual_item_receipt_moves_responsibility(self):
        laptop = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        p = laptop.portions.get()
        a = actor(self.w.custodian)
        with transaction.atomic():
            InventoryLedger.claim(a, candidate_portion_ids=[p.pk], quantity=1, claim_ref="r:3")
            InventoryLedger.commit(a, claim_ref="r:3")
            InventoryLedger.dispatch(a, claim_ref="r:3", quantity=1, consignment_ref="c:3", temporary_custodian=None)
            InventoryLedger.accept_receipt(a, consignment_ref="c:3", quantity=1, department=self.w.other,
                                           location=self.w.other_loc, custodian=self.w.other_custodian)
        laptop.refresh_from_db()
        self.assertEqual((laptop.department_id, laptop.custodian_id, laptop.location_id),
                         (self.w.other.pk, self.w.other_custodian.pk, self.w.other_loc.pk))
        self.assertEqual(laptop.legal_owner, "Khalifa University")

    def test_unsafe_units_cannot_be_held_or_dispatched(self):
        a = actor(self.w.custodian)
        with transaction.atomic():
            InventoryLedger.record_safety(a, self.root.pk, SafetyState.RESTRICTED, evidence_ref="inspection:9")
        with self.assertRaises(StockConflict), transaction.atomic():
            InventoryLedger.claim(a, candidate_portion_ids=[self.root.pk], quantity=1, claim_ref="r:4")

    def test_new_safety_problem_blocks_held_units_without_releasing(self):
        a = actor(self.w.custodian)
        with transaction.atomic():
            (held_id,) = InventoryLedger.claim(a, candidate_portion_ids=[self.root.pk], quantity=3, claim_ref="r:5")
            InventoryLedger.record_safety(a, held_id, SafetyState.RESTRICTED, evidence_ref="defect:1")
        held = AssetPortion.objects.get(pk=held_id)
        self.assertEqual((held.allocation, held.safety_state), (Allocation.HELD, SafetyState.RESTRICTED))
        with self.assertRaises(StockConflict), transaction.atomic():
            InventoryLedger.commit(a, claim_ref="r:5")

    def test_release_returns_undispatched_units_once(self):
        a = actor(self.w.custodian, "release-1")
        with transaction.atomic():
            InventoryLedger.claim(actor(self.w.custodian), candidate_portion_ids=[self.root.pk], quantity=4,
                                  claim_ref="r:6")
        for _ in range(2):
            with transaction.atomic():
                InventoryLedger.release_claim(a, claim_ref="r:6", reason="Hold expired")
        free = AssetPortion.objects.filter(asset=self.chairs, allocation=Allocation.FREE, is_active_leaf=True)
        self.assertEqual(sum(p.quantity for p in free), 10)
        self.assertConserved()

    def test_lost_units_never_return(self):
        a = actor(self.w.custodian)
        with transaction.atomic():
            InventoryLedger.claim(a, candidate_portion_ids=[self.root.pk], quantity=2, claim_ref="r:7")
            InventoryLedger.commit(a, claim_ref="r:7")
            InventoryLedger.dispatch(a, claim_ref="r:7", quantity=2, consignment_ref="c:7", temporary_custodian=None)
            InventoryLedger.record_lost(a, consignment_ref="c:7", quantity=1, reference="loss:1")
            InventoryLedger.record_return(a, consignment_ref="c:7", quantity=1, location=self.w.loc)
        lost = AssetPortion.objects.get(asset=self.chairs, lifecycle_state=Lifecycle.LOST)
        returned = AssetPortion.objects.get(asset=self.chairs, lifecycle_state=Lifecycle.UNDER_INSPECTION)
        self.assertEqual((lost.quantity, returned.quantity), (1, 1))
        with self.assertRaises(ValidationFailed), transaction.atomic():
            InventoryLedger.change_lifecycle(a, lost.pk, Lifecycle.AVAILABLE)
        self.assertConserved()

    def test_adjustment_cannot_reduce_claimed_stock(self):
        a = actor(self.w.custodian)
        with transaction.atomic():
            (held,) = InventoryLedger.claim(a, candidate_portion_ids=[self.root.pk], quantity=4, claim_ref="r:8")
        portion = AssetPortion.objects.get(pk=held)
        with self.assertRaises(StockConflict), transaction.atomic():
            InventoryLedger.adjust(a, held, 1, reason="Recount", expected_version=portion.version)
        free = AssetPortion.objects.get(asset=self.chairs, allocation=Allocation.FREE)
        InventoryService.adjust_quantity(a, free.pk, 5, reason="Recount found one broken", expected_version=free.version)
        self.assertConserved()  # adjustment event explains the change
        self.assertEqual(InventoryLedger.expected_total(self.chairs), 9)

    def test_final_execution_requires_evidence_and_commitment(self):
        a = actor(self.w.custodian)
        with transaction.atomic():
            InventoryLedger.claim(a, candidate_portion_ids=[self.root.pk], quantity=3, claim_ref="final:1",
                                  allocation=Allocation.FINAL_COMMITTED)
        with self.assertRaises(ValidationFailed), transaction.atomic():
            InventoryLedger.execute_final(a, claim_ref="final:1", quantity=3, outcome=Lifecycle.RECYCLED,
                                          reference="final:1")
        with transaction.atomic():
            InventoryLedger.execute_final(a, claim_ref="final:1", quantity=2, outcome=Lifecycle.RECYCLED,
                                          reference="final:1", evidence_refs=["certificate:44"])
        recycled = AssetPortion.objects.get(asset=self.chairs, lifecycle_state=Lifecycle.RECYCLED)
        remaining = AssetPortion.objects.get(asset=self.chairs, allocation=Allocation.FINAL_COMMITTED)
        self.assertEqual((recycled.quantity, remaining.quantity), (2, 1))
        self.assertConserved()

    def test_failed_transaction_leaves_no_partial_change(self):
        a = actor(self.w.custodian)
        try:
            with transaction.atomic():
                InventoryLedger.claim(a, candidate_portion_ids=[self.root.pk], quantity=4, claim_ref="r:9")
                raise RuntimeError("simulated workflow failure after the ledger write")
        except RuntimeError:
            pass
        self.root.refresh_from_db()
        self.assertEqual(self.root.quantity, 10)
        self.assertFalse(AssetEvent.objects.filter(event_type=AssetEventType.HELD).exists())
        self.assertConserved()


class LastUnitRaceTests(TransactionTestCase):
    """NFR-04: twenty simultaneous holds for the last unit produce exactly one."""

    serialized_rollback = True  # keep migration-seeded roles between tests

    def test_ledger_requires_caller_transaction(self):
        w = World()
        chairs = batch(w.custodian, w.dept, w.loc, w.cat, quantity=4)
        with self.assertRaises(RuntimeError):
            InventoryLedger.split(actor(w.custodian), chairs.portions.get().pk, 2)

    def test_twenty_competing_claims_one_success(self):
        if connection.vendor == "sqlite" and connection.is_in_memory_db():
            self.skipTest("Needs a file or PostgreSQL database for real concurrency.")
        w = World()
        asset = register(w.custodian, w.dept, w.loc, w.cat)
        portion_id = asset.portions.get().pk
        results = []
        barrier = threading.Barrier(20)

        def attempt(i):
            from django.db import connections

            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    InventoryLedger.claim(actor(w.custodian), candidate_portion_ids=[portion_id], quantity=1,
                                          claim_ref=f"race:{i}")
                results.append("ok")
            except StockConflict:
                results.append("conflict")
            except Exception as exc:  # noqa: BLE001 - lock timeouts count as failed attempts
                results.append(type(exc).__name__)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count("ok"), 1, results)
        self.assertEqual(AssetPortion.objects.filter(allocation=Allocation.HELD).count(), 1)
        ok, _, _ = InventoryLedger.verify_conservation(asset)
        self.assertTrue(ok)


class AttachmentTests(TestCase):
    def setUp(self):
        self.w = World()
        self.asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)

    def upload(self, name, data, access=AttachmentAccess.RESTRICTED, user=None):
        return AttachmentService.store(actor(user or self.w.custodian), self.asset,
                                       SimpleUploadedFile(name, data), access_class=access)

    def test_valid_png_and_pdf_accepted(self):
        self.assertEqual(self.upload("photo.png", png_bytes()).status, "ACCEPTED")
        self.assertEqual(self.upload("manual.pdf", PDF).status, "ACCEPTED")

    def test_wrong_type_rejected_by_content_not_name(self):
        with self.assertRaises(ValidationFailed):
            self.upload("fake.png", b"MZ\x90\x00 executable")
        with self.assertRaises(ValidationFailed):
            self.upload("notes.txt", b"plain text")

    def test_oversized_file_rejected(self):
        with self.assertRaises(ValidationFailed):
            self.upload("big.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024 + 1))

    def test_unreadable_or_active_content_quarantined(self):
        broken = self.upload("broken.png", b"\x89PNG\r\n\x1a\n" + b"garbage")
        self.assertEqual(broken.status, "QUARANTINED")
        scripted = self.upload("script.pdf", b"%PDF-1.4\n/OpenAction << /JS (app.alert(1)) >>\n%%EOF")
        self.assertEqual(scripted.status, "QUARANTINED")
        client = Client()
        sign_in(client, self.w.custodian)
        self.assertEqual(client.get(f"/inventory/evidence/{broken.pk}/").status_code, 404)

    def test_ten_file_limit(self):
        for i in range(10):
            self.upload(f"p{i}.png", png_bytes())
        with self.assertRaises(ValidationFailed):
            self.upload("eleven.png", png_bytes())

    def test_malicious_filename_is_sanitised(self):
        att = self.upload("../../etc/passwd<script>.png", png_bytes())
        self.assertNotIn("/", att.original_name)
        self.assertNotIn("<", att.original_name)

    def test_download_permissions(self):
        restricted = self.upload("invoice.pdf", PDF)
        photo = self.upload("photo.png", png_bytes(), access=AttachmentAccess.CATALOGUE_PHOTO)
        client = Client()
        sign_in(client, self.w.requester)
        self.assertEqual(client.get(f"/inventory/evidence/{restricted.pk}/").status_code, 404)
        self.assertEqual(client.get(f"/inventory/evidence/{photo.pk}/").status_code, 404)  # not yet published
        sign_in(client, self.w.custodian)
        response = client.get(f"/inventory/evidence/{restricted.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_only_assigned_custodian_uploads(self):
        with self.assertRaises(NotPermitted):
            self.upload("p.png", png_bytes(), user=self.w.rep)
