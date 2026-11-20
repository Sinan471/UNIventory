import csv
from django.http import HttpResponse
from django.shortcuts import render
from core.web import active_role_required
from identity.models import Role
from identity.policy import AccessPolicy
from .models import AuditLog


def is_campus_auditor(user):
    return any(g.role == Role.AUDITOR and g.department_id is None for g in AccessPolicy.grants(user))


def records(request):
    rows = AuditLog.objects.select_related("actor")
    query = request.GET.get("action", "").strip()[:100]
    if query:
        rows = rows.filter(action__icontains=query)
    return rows


def denied(request):
    return render(request, "core/error.html", {"status": 403, "message": "Campus audit access is required."}, status=403)


@active_role_required
def audit_list(request):
    if not is_campus_auditor(request.user):
        return denied(request)
    return render(request, "audit/list.html", {"rows": records(request)[:500], "action": request.GET.get("action", "")})


@active_role_required
def export(request):
    if not is_campus_auditor(request.user):
        return denied(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="audit.csv"'
    writer = csv.writer(response)
    writer.writerow(["Time", "Actor", "Action", "Target type", "Target ID", "Outcome", "Reason"])
    def safe(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    for row in records(request).iterator():
        writer.writerow([safe(row.occurred_at.isoformat()), safe(row.actor_id), safe(row.action), safe(row.target_type), safe(row.target_id), safe(row.outcome), safe(row.reason)])
    return response
