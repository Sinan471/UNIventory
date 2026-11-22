
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .monitoring import AIMonitoringService


@login_required
def monitoring_dashboard(request):
    summary = AIMonitoringService.get_summary()

    return render(
        request,
        "ai/monitoring.html",
        {"summary": summary}
    )
