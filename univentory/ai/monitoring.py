
from django.db.models import Sum, Count, Q
from .models import AIRun


class AIMonitoringService:

    @staticmethod
    def get_summary():
        runs = AIRun.objects.all()

        totals = runs.aggregate(
            total=Count("id"),
            completed=Count(
                "id", filter=Q(status=AIRun.Status.COMPLETED)
            ),
            failed=Count(
                "id", filter=Q(status=AIRun.Status.FAILED)
            ),
            timed_out=Count(
                "id", filter=Q(status=AIRun.Status.TIMEOUT)
            ),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
            reserved_cost=Sum("reserved_cost_aed"),
            actual_cost=Sum("actual_cost_aed"),
        )

        return {
            "total_runs": totals["total"] or 0,
            "completed_runs": totals["completed"] or 0,
            "failed_runs": totals["failed"] or 0,
            "timed_out_runs": totals["timed_out"] or 0,
            "input_tokens": totals["input_tokens"] or 0,
            "output_tokens": totals["output_tokens"] or 0,
            "reserved_cost_aed": totals["reserved_cost"] or 0,
            "actual_cost_aed": totals["actual_cost"] or 0,
            "recent_runs": runs.order_by("-created_at")[:10],
        }
