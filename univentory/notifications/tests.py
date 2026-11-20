from django.test import TestCase
from django.urls import reverse
from core.testing import World
from .services import NotificationService


class NotificationTests(TestCase):
    def test_only_recipient_can_read_or_mark_notice(self):
        world = World()
        row = NotificationService.notify(world.requester, "A request has changed.")
        self.client.force_login(world.custodian)
        self.assertNotContains(self.client.get(reverse("notifications:list")), row.message)
        self.assertEqual(self.client.post(reverse("notifications:read", args=[row.pk])).status_code, 404)
        self.client.force_login(world.requester)
        self.assertContains(self.client.get(reverse("notifications:list")), row.message)
        self.client.post(reverse("notifications:read", args=[row.pk]))
        row.refresh_from_db()
        self.assertIsNotNone(row.read_at)
