from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from core.contracts import NotPermitted, StaleVersion
from identity.models import Role, UserRole
from core.testing import World
from .models import ResourceRequest
from .services import DemandService


class RequestTests(TestCase):
    def setUp(self):
        self.world = World()
        self.data = {"department": self.world.other, "title": "Chairs", "purpose": "Teaching room",
                     "specifications": "Stackable", "quantity": Decimal("3"), "needed_by": None,
                     "urgent": False, "urgent_reason": ""}

    def test_draft_submit_and_cancel(self):
        item = DemandService.save(self.world.requester, self.data)
        self.assertEqual(item.state, ResourceRequest.State.DRAFT)
        item = DemandService.save(self.world.requester, self.data, request_id=item.pk, expected_version=1, submit=True)
        self.assertEqual(item.state, ResourceRequest.State.SUBMITTED)
        self.assertEqual(item.events.count(), 2)
        with self.assertRaises(StaleVersion):
            DemandService.cancel(self.world.requester, item.pk, 1)
        DemandService.cancel(self.world.requester, item.pk, 2)
        item.refresh_from_db()
        self.assertEqual(item.state, ResourceRequest.State.CANCELLED)

    def test_department_authorisation(self):
        self.data["department"] = self.world.dept
        with self.assertRaises(NotPermitted):
            DemandService.save(self.world.requester, self.data)

    def test_other_users_cannot_read_request(self):
        item = DemandService.save(self.world.requester, self.data)
        self.client.force_login(self.world.custodian)
        self.assertEqual(self.client.get(reverse("demand:detail", args=[item.pk])).status_code, 404)

    def test_urgent_reason_required(self):
        self.client.force_login(self.world.requester)
        response = self.client.post(reverse("demand:new"), {"department": self.world.other.pk,
            "title": "Chairs", "purpose": "Teaching", "quantity": "2", "urgent": "on", "action": "submit", "operation_key": "test-key"})
        self.assertContains(response, "Explain why this request is urgent")
        self.assertFalse(ResourceRequest.objects.exists())

    def test_request_submission_replays_same_operation(self):
        first = DemandService.save(self.world.requester, self.data, submit=True, operation_key="request-key")
        second = DemandService.save(self.world.requester, self.data, submit=True, operation_key="request-key")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ResourceRequest.objects.count(), 1)

    def test_revoked_requester_cannot_read_even_with_another_role(self):
        item = DemandService.save(self.world.requester, self.data)
        UserRole.objects.filter(user=self.world.requester, role__code=Role.REQUESTER).delete()
        UserRole.objects.create(user=self.world.requester, role=Role.objects.get(code=Role.CAMPUS_USER), department=self.world.other)
        self.client.force_login(self.world.requester)
        self.assertEqual(self.client.get(reverse("demand:detail", args=[item.pk])).status_code, 404)
