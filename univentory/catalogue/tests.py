"""Publication, listing control and search tests (FR-11..FR-14, FR-19, FR-20, BR-02, BR-08)."""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, TestCase

from catalogue.models import Listing, ListingState
from catalogue.services import CatalogueQueryService, CatalogueService
from core.contracts import NotPermitted, StaleVersion, StockConflict, ValidationFailed, get_adapter
from core.contracts.approvals import ReleaseStatus
from core.testing import World, actor, approve_release, batch, register
from core.testing import user as make_user
from identity.tests import sign_in
from inventory.ledger import InventoryLedger
from inventory.models import Allocation, AssetPortion, AttachmentAccess, Condition, Lifecycle, SafetyState
from inventory.services import AttachmentService, InventoryService


def make_listing(w, asset, qty=None, **kw):
    portion = asset.portions.filter(is_active_leaf=True).first()
    return CatalogueService.create(
        actor(w.custodian), asset=asset, title=kw.get("title", asset.title),
        public_description=kw.get("public_description", "Good condition, collect from store."),
        offered_quantity=qty or portion.quantity, collection_info="Building A store, Sun-Thu",
    )


def publish(w, asset, qty=None):
    listing = make_listing(w, asset, qty)
    listing = CatalogueService.transition(actor(w.custodian), listing.pk, "submit", expected_version=listing.version)
    approve_release(listing, w.rep)
    return CatalogueService.transition(actor(w.custodian), listing.pk, "publish", expected_version=listing.version)


class ListingLifecycleTests(TestCase):
    def setUp(self):
        self.w = World()
        self.chairs = batch(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, quantity=10)

    def test_cannot_offer_more_than_releasable(self):
        with self.assertRaises(ValidationFailed) as ctx:
            make_listing(self.w, self.chairs, qty=Decimal(11))
        self.assertIn("offered_quantity", ctx.exception.field_errors)

    def test_only_assigned_custodian_lists(self):
        with self.assertRaises(NotPermitted):
            CatalogueService.create(actor(self.w.rep), asset=self.chairs, title="x", public_description="y",
                                    offered_quantity=1, collection_info="z")

    def test_publication_requires_current_release_approval(self):
        listing = make_listing(self.w, self.chairs)
        listing = CatalogueService.transition(actor(self.w.custodian), listing.pk, "submit",
                                              expected_version=listing.version)
        with self.assertRaises(ValidationFailed) as ctx:
            CatalogueService.transition(actor(self.w.custodian), listing.pk, "publish", expected_version=listing.version)
        self.assertTrue(any("release approval" in r for r in ctx.exception.field_errors["__all__"]))
        listing.refresh_from_db()
        self.assertEqual(listing.state, ListingState.AWAITING_RELEASE)

    def test_proposer_cannot_self_approve_release(self):
        listing = make_listing(self.w, self.chairs)
        listing = CatalogueService.transition(actor(self.w.custodian), listing.pk, "submit",
                                              expected_version=listing.version)
        with self.assertRaises(NotPermitted):
            get_adapter("RELEASE_APPROVALS").decide(listing=listing, decider=self.w.custodian,
                                                    status=ReleaseStatus.APPROVED)
        with self.assertRaises(NotPermitted):  # rep of another department
            other_rep = make_user("orep", ("DEPT_REP", self.w.other))
            get_adapter("RELEASE_APPROVALS").decide(listing=listing, decider=other_rep, status=ReleaseStatus.APPROVED)

    def test_each_blocking_condition_reported(self):
        unsafe = batch(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, quantity=3, cleared=False,
                       title="Uncleared")
        restricted = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, ownership_restriction="LEASED",
                              restriction_notes="Lease ends 2027", title="Leased printer")
        for asset, phrase in ((unsafe, "safety clearance"), (restricted, "restrictions are unresolved")):
            listing = make_listing(self.w, asset)
            listing = CatalogueService.transition(actor(self.w.custodian), listing.pk, "submit",
                                                  expected_version=listing.version)
            approve_release(listing, self.w.rep)
            with self.subTest(phrase=phrase), self.assertRaises(ValidationFailed) as ctx:
                CatalogueService.transition(actor(self.w.custodian), listing.pk, "publish",
                                            expected_version=listing.version)
            self.assertTrue(any(phrase in r for r in ctx.exception.field_errors["__all__"]), ctx.exception.field_errors)
            listing.refresh_from_db()
            self.assertNotEqual(listing.state, ListingState.PUBLISHED)

    def test_returned_release_goes_back_to_draft(self):
        listing = make_listing(self.w, self.chairs)
        listing = CatalogueService.transition(actor(self.w.custodian), listing.pk, "submit",
                                              expected_version=listing.version)
        get_adapter("RELEASE_APPROVALS").decide(listing=listing, decider=self.w.rep, status=ReleaseStatus.RETURNED,
                                                reason="Add photos")
        listing = CatalogueService.sync_release_outcome(listing)
        self.assertEqual(listing.state, ListingState.DRAFT)
        self.assertIn("Add photos", listing.state_reason)

    def test_publish_pause_resume_withdraw(self):
        listing = publish(self.w, self.chairs)
        self.assertEqual(listing.state, ListingState.PUBLISHED)
        self.assertEqual(CatalogueService.free_quantity(listing), 10)
        listing = CatalogueService.transition(actor(self.w.custodian), listing.pk, "pause",
                                              expected_version=listing.version, reason="Stock check")
        self.assertEqual(CatalogueService.free_quantity(listing), 0)
        with self.assertRaises(StockConflict), transaction.atomic():
            CatalogueService.hold(actor(self.w.requester), listing_id=listing.pk, quantity=1, claim_ref="r:1")
        listing = CatalogueService.transition(actor(self.w.custodian), listing.pk, "resume",
                                              expected_version=listing.version)
        self.assertEqual(listing.state, ListingState.PUBLISHED)
        with self.assertRaises(ValidationFailed):  # reason required
            CatalogueService.transition(actor(self.w.custodian), listing.pk, "withdraw", expected_version=listing.version)
        with self.assertRaises(StaleVersion):
            CatalogueService.transition(actor(self.w.custodian), listing.pk, "withdraw", expected_version=1,
                                        reason="Needed")

    def test_resume_rechecks_eligibility(self):
        listing = publish(self.w, self.chairs)
        listing = CatalogueService.transition(actor(self.w.custodian), listing.pk, "pause",
                                              expected_version=listing.version, reason="Defect reported")
        portion = self.chairs.portions.get()
        with transaction.atomic():
            InventoryLedger.record_safety(actor(self.w.custodian), portion.pk, SafetyState.RESTRICTED,
                                          evidence_ref="defect:3")
        with self.assertRaises(ValidationFailed):
            CatalogueService.transition(actor(self.w.custodian), listing.pk, "resume", expected_version=listing.version)

    def test_hold_through_listing_and_free_quantity(self):
        listing = publish(self.w, self.chairs, qty=Decimal(6))
        self.assertEqual(CatalogueService.free_quantity(listing), 6)
        with transaction.atomic():
            CatalogueService.hold(actor(self.w.rep), listing_id=listing.pk, quantity=4, claim_ref="reservation:1")
        self.assertEqual(CatalogueService.free_quantity(listing), 2)  # offered 6, claimed 4
        with self.assertRaises(StockConflict), transaction.atomic():
            CatalogueService.hold(actor(self.w.rep), listing_id=listing.pk, quantity=3, claim_ref="reservation:2")
        with transaction.atomic():
            InventoryLedger.release_claim(actor(self.w.rep), claim_ref="reservation:1", reason="Expired")
        self.assertEqual(CatalogueService.free_quantity(listing), 6)

    def test_last_unit_cannot_be_held_twice(self):
        laptop = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        listing = publish(self.w, laptop)
        with transaction.atomic():
            CatalogueService.hold(actor(self.w.rep), listing_id=listing.pk, quantity=1, claim_ref="reservation:a")
        for i in range(5):
            with self.assertRaises(StockConflict), transaction.atomic():
                CatalogueService.hold(actor(self.w.rep), listing_id=listing.pk, quantity=1, claim_ref=f"reservation:b{i}")
        self.assertEqual(AssetPortion.objects.filter(asset=laptop, allocation=Allocation.HELD).count(), 1)

    def test_material_change_supersedes_release_and_pauses(self):
        listing = publish(self.w, self.chairs)
        self.chairs.refresh_from_db()
        InventoryService.update(actor(self.w.custodian), self.chairs.pk,
                                {"ownership_restriction": "SPONSORED", "restriction_notes": "Grant asset"},
                                expected_version=self.chairs.version)
        listing.refresh_from_db()
        self.assertEqual(listing.state, ListingState.PAUSED)
        self.assertIn("release review required", listing.state_reason)
        decision = get_adapter("RELEASE_APPROVALS").current_decision(listing=listing)
        self.assertEqual(decision.status, ReleaseStatus.SUPERSEDED)
        with self.assertRaises(ValidationFailed):
            CatalogueService.transition(actor(self.w.custodian), listing.pk, "resume", expected_version=listing.version)


class SearchTests(TestCase):
    def setUp(self):
        self.w = World()
        self.laptop = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, title="Dell laptop",
                               condition=Condition.GOOD)
        self.scope = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, title="Olympus microscope",
                              description="Binocular teaching microscope", condition=Condition.FAIR,
                              estimated_value_aed=Decimal("9000"))
        self.hidden = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat, title="Secret prototype rig")
        self.l1 = publish(self.w, self.laptop)
        self.l2 = publish(self.w, self.scope)
        make_listing(self.w, self.hidden)  # draft only: must not be visible or counted

    def search(self, **params):
        return list(CatalogueQueryService.search(self.w.requester, params))

    def test_keyword_and_filters(self):
        self.assertEqual([l.pk for l in self.search(q="microscope")], [self.l2.pk])
        self.assertEqual([l.pk for l in self.search(condition="GOOD")], [self.l1.pk])
        self.assertEqual([l.pk for l in self.search(value_min=5000)], [self.l2.pk])
        self.assertEqual(len(self.search(department=self.w.other.pk)), 0)
        self.assertEqual({l.pk for l in self.search(sort="title")}, {self.l1.pk, self.l2.pk})
        self.assertEqual(len(self.search(q=self.laptop.asset_code)), 1)

    def test_restricted_records_excluded_from_results_and_counts(self):
        self.assertEqual(len(self.search()), 2)
        self.assertEqual(self.search(q="Secret"), [])
        client = Client()
        sign_in(client, self.w.requester)
        response = client.get("/exchange/", {"q": "Secret"})
        self.assertContains(response, "0 listings")
        self.assertContains(response, "No matching items found")
        draft = Listing.objects.get(asset=self.hidden)
        self.assertEqual(client.get(f"/exchange/listings/{draft.pk}/").status_code, 404)

    def test_availability_filter_hides_fully_held(self):
        with transaction.atomic():
            CatalogueService.hold(actor(self.w.rep), listing_id=self.l1.pk, quantity=1, claim_ref="reservation:x")
        self.assertEqual([l.pk for l in self.search()], [self.l2.pk])
        self.assertEqual(len(self.search(availability="all")), 2)

    def test_listing_page_hides_restricted_evidence(self):
        AttachmentService.store(actor(self.w.custodian), self.laptop,
                                SimpleUploadedFile("quote.pdf", b"%PDF-1.4\n%%EOF\n"),
                                access_class=AttachmentAccess.RESTRICTED)
        client = Client()
        sign_in(client, self.w.requester)
        response = client.get(f"/exchange/listings/{self.l1.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "quote.pdf")
        self.assertNotContains(response, self.w.custodian.email)

    def test_exchange_page_renders_grid_and_list(self):
        client = Client()
        sign_in(client, self.w.requester)
        for view in ("grid", "list"):
            response = client.get("/exchange/", {"view": view, "q": "laptop"})
            self.assertContains(response, "Dell laptop")
