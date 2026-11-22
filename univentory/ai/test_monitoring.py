
from django.test import TestCase
from .models import AIRun
from .monitoring import AIMonitoringService


class AIMonitoringTest(TestCase):

    def test_empty_summary(self):
        result = AIMonitoringService.get_summary()

        self.assertEqual(result["total_runs"], 0)
        self.assertEqual(result["completed_runs"], 0)
        self.assertEqual(result["failed_runs"], 0)

    def test_completed_run_count(self):
        AIRun.objects.create(
            task_type=AIRun.TaskType.CLASSIFICATION,
            status=AIRun.Status.COMPLETED
        )

        result = AIMonitoringService.get_summary()

        self.assertEqual(result["total_runs"], 1)
        self.assertEqual(result["completed_runs"], 1)
