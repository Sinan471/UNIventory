from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from core.contracts.audit import AuditEntry
from core.testing import World
from core.testing import user
from identity.models import Role
from .models import AuditLog
from .services import AuditService


class AuditTests(TestCase):
    def test_append_and_rollback(self):
        world = World()
        entry = AuditEntry(action="request.submit", target_type="Request", target_id="1", actor_id=world.requester.pk)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                AuditService().record(entry)
                raise RuntimeError("rollback")
        self.assertFalse(AuditLog.objects.exists())
        row = AuditService().record(entry)
        row.reason = "changed"
        with self.assertRaises(ValidationError):
            row.save()
        with self.assertRaises(ValidationError):
            row.delete()
        with self.assertRaises(ValidationError):
            AuditLog.objects.filter(pk=row.pk).update(reason="changed")
        with self.assertRaises(ValidationError):
            AuditLog.objects.filter(pk=row.pk).delete()

    def test_export_requires_campus_auditor_and_neutralizes_formulas(self):
        world = World()
        AuditService().record(AuditEntry(action="test", target_type="Request", target_id="1", actor_id=world.requester.pk, reason="=1+1"))
        self.client.force_login(world.requester)
        self.assertEqual(self.client.get(reverse("audit:export")).status_code, 403)
        auditor = user("auditor", (Role.AUDITOR, None))
        self.client.force_login(auditor)
        result = self.client.get(reverse("audit:export"))
        self.assertEqual(result.status_code, 200)
        self.assertIn("'=1+1", result.content.decode())
