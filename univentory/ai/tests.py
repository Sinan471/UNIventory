
from django.test import TestCase
from .models import AIRun, ModelVersion
from .services import AIGateway


class AIGatewayTest(TestCase):

    def setUp(self):
        self.model = ModelVersion.objects.create(
            provider="LOCAL",
            model_name="Test Model",
            version="1.0",
            supported_tasks=["CLASSIFICATION"]
        )

    def test_create_ai_run(self):
        run = AIGateway.create_run(
            user=None,
            task_type=AIRun.TaskType.CLASSIFICATION
        )

        self.assertEqual(run.status, AIRun.Status.PENDING)
        self.assertEqual(run.model_version, self.model)

    def test_execute_ai_run(self):
        run = AIGateway.create_run(
            user=None,
            task_type=AIRun.TaskType.CLASSIFICATION
        )

        run = AIGateway.execute(
            run,
            lambda: {"category": "Furniture"}
        )

        self.assertEqual(run.status, AIRun.Status.COMPLETED)
        self.assertEqual(run.result["category"], "Furniture")
