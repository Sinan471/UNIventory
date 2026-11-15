from decimal import Decimal
from django.test import TestCase, override_settings
from core.contracts import NotPermitted, StaleVersion, ValidationFailed
from core.testing import World, user
from demand.models import ResourceRequest
from demand.services import DemandService
from identity.models import Role
from identity.models import UserRole
from identity.policy import AccessPolicy
from .services import ApprovalService
from .adapters import ReleaseApprovals
from core.contracts.registry import reset_adapters
from core.contracts.approvals import ReleaseStatus
from core.testing import actor, batch
from catalogue.services import CatalogueService
from catalogue.tests import make_listing


class ApprovalTests(TestCase):
    def setUp(self):
        self.world = World()
        self.rep = user("science_rep", (Role.DEPT_REP, self.world.other))
        self.item = DemandService.save(self.world.requester, {"department": self.world.other, "title": "Chairs",
            "purpose": "Classroom", "specifications": "", "quantity": Decimal("2"), "needed_by": None,
            "urgent": False, "urgent_reason": ""}, submit=True)

    def test_only_independent_department_representative_can_decide(self):
        with self.assertRaises(NotPermitted):
            ApprovalService.decide_request(self.world.rep, self.item.pk, 1, "approve")
        with self.assertRaises(NotPermitted):
            ApprovalService.decide_request(self.world.requester, self.item.pk, 1, "approve")
        UserRole.objects.create(user=self.world.requester, role=Role.objects.get(code=Role.DEPT_REP), department=self.world.other)
        AccessPolicy.refresh(self.world.requester)
        with self.assertRaises(NotPermitted):
            ApprovalService.decide_request(self.world.requester, self.item.pk, 1, "approve")
        ApprovalService.decide_request(self.rep, self.item.pk, 1, "approve")
        self.item.refresh_from_db()
        self.assertEqual(self.item.state, ResourceRequest.State.APPROVED)
        with self.assertRaises(StaleVersion):
            ApprovalService.decide_request(self.rep, self.item.pk, 1, "approve")

    def test_return_requires_reason_and_allows_revision(self):
        with self.assertRaises(ValidationFailed):
            ApprovalService.decide_request(self.rep, self.item.pk, 1, "return")
        ApprovalService.decide_request(self.rep, self.item.pk, 1, "return", "Add details")
        self.item.refresh_from_db()
        self.assertEqual(self.item.state, ResourceRequest.State.RETURNED)
        self.assertEqual(self.item.decisions.get().reason, "Add details")


@override_settings(UNIVENTORY_CONTRACT_ADAPTERS={"RELEASE_APPROVALS": "workflow.adapters.ReleaseApprovals", "AUDIT": "audit.services.AuditService"})
class ReleaseIntegrationTests(TestCase):
    def setUp(self):
        reset_adapters()
        self.addCleanup(reset_adapters)
        self.world = World()

    def test_listing_release_requires_independent_current_review(self):
        asset = batch(self.world.custodian, self.world.dept, self.world.loc, self.world.cat)
        listing = make_listing(self.world, asset)
        listing = CatalogueService.transition(actor(self.world.custodian), listing.pk, "submit", expected_version=listing.version)
        adapter = ReleaseApprovals()
        with self.assertRaises(NotPermitted):
            adapter.decide(listing_id=listing.pk, decider=self.world.custodian, expected_version=listing.version, status=ReleaseStatus.APPROVED)
        with self.assertRaises(StaleVersion):
            adapter.decide(listing_id=listing.pk, decider=self.world.rep, expected_version=1, status=ReleaseStatus.APPROVED)
        result = adapter.decide(listing_id=listing.pk, decider=self.world.rep, expected_version=listing.version, status=ReleaseStatus.APPROVED)
        self.assertFalse(result.is_test_adapter)
        listing = CatalogueService.transition(actor(self.world.custodian), listing.pk, "publish", expected_version=listing.version)
        self.assertEqual(listing.state, "PUBLISHED")
