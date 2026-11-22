
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404

from .services import ReportingService
from .models import ReportSnapshot


@login_required
def export_report_csv(request, snapshot_id):
    if not ReportSnapshot.objects.filter(pk=snapshot_id).exists():
        raise Http404("Report not found.")

    csv_content = ReportingService.export_csv(snapshot_id)

    response = HttpResponse(
        csv_content,
        content_type="text/csv; charset=utf-8",
    )

    response["Content-Disposition"] = (
        f'attachment; filename="report_{snapshot_id}.csv"'
    )

    return response
