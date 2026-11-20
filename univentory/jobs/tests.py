from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from .models import WorkItem
from .services import WorkDispatcher


class WorkerTests(TestCase):
    def test_unknown_job_retries_then_fails(self):
        item = WorkItem.objects.create(kind="unknown", object_id=1, due_at=timezone.now())
        for _ in range(WorkDispatcher.MAX_ATTEMPTS):
            WorkItem.objects.filter(pk=item.pk).update(due_at=timezone.now() - timedelta(seconds=1))
            self.assertFalse(WorkDispatcher.run_one(item.pk))
        item.refresh_from_db()
        self.assertEqual(item.state, WorkItem.State.FAILED)
        self.assertEqual(item.attempts, WorkDispatcher.MAX_ATTEMPTS)
