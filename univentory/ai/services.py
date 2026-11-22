
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from .models import AIRun, ModelVersion


class AIGateway:

    @staticmethod
    def get_model(task_type):
        models = ModelVersion.objects.filter(is_active=True)

        for model in models:
            if task_type in model.supported_tasks:
                return model

        return None

    @staticmethod
    def create_run(user, task_type, deadline=None,
                   prompt_version="1.0", schema_version="1.0"):

        model = AIGateway.get_model(task_type)

        return AIRun.objects.create(
            user=user,
            model_version=model,
            task_type=task_type,
            status=AIRun.Status.PENDING,
            deadline=deadline,
            prompt_version=prompt_version,
            schema_version=schema_version
        )

    @staticmethod
    @transaction.atomic
    def execute(run, handler, *args, **kwargs):

        run = AIRun.objects.select_for_update().get(pk=run.pk)

        if run.status != AIRun.Status.PENDING:
            raise ValueError("AI run is not pending.")

        if run.deadline and timezone.now() >= run.deadline:
            run.status = AIRun.Status.TIMEOUT
            run.failure_code = "DEADLINE_EXCEEDED"
            run.failure_message = "AI task deadline exceeded."
            run.completed_at = timezone.now()
            run.save()
            return run

        if not run.model_version or not run.model_version.is_active:
            run.mark_failed(
                "MODEL_UNAVAILABLE",
                "No active AI model is available."
            )
            return run

        run.mark_running()

        try:
            result = handler(*args, **kwargs)

            if not isinstance(result, dict):
                raise ValueError("AI handler must return a dictionary.")

            run.mark_completed(result)

        except Exception as error:
            run.mark_failed(
                "EXECUTION_ERROR",
                str(error)[:500]
            )

        return run

    @staticmethod
    def record_usage(run, input_tokens=0,
                     output_tokens=0, cost_aed=Decimal("0")):

        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts cannot be negative.")

        cost = Decimal(str(cost_aed))

        if cost < 0:
            raise ValueError("Cost cannot be negative.")

        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.actual_cost_aed = cost
        run.save(update_fields=[
            "input_tokens",
            "output_tokens",
            "actual_cost_aed"
        ])
