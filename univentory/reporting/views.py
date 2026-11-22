"""Operational reports, CSV export and report narratives (owner: Jessica).

C9 / FR-48 / FR-49: filterable request and transfer tables; the CSV contains
exactly the permitted on-screen rows, with filters, units and generation time
and spreadsheet formulas neutralised.
AI-09 / AI-10: a narrative is drafted from an immutable snapshot, edited by a
person, checked so every number still matches the snapshot, then published.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.csvsafe import safe_row
from core.web import active_role_required, permission_denied_response
from identity.models import Department, Role
from identity.policy import AccessPolicy

from .models import ReportSnapshot
from .services import ReportingService, ReportPublicationService

CAMPUS_ROLES = {Role.SUSTAINABILITY, Role.MANAGEMENT, Role.PROCUREMENT, Role.FINANCE, Role.AUDITOR,
                Role.REPORT_PUBLISHER}


def scope_departments(user) -> list[int] | None:
    """Department IDs the user may report on; None means none at all."""
    codes = AccessPolicy.role_codes(user)
    if codes & CAMPUS_ROLES:
        return list(Department.objects.values_list("pk", flat=True))
    reps = AccessPolicy.departments_with_role(user, Role.DEPT_REP)
    return reps or None


def can_publish(user) -> bool:
    return AccessPolicy.has_role(user, Role.REPORT_PUBLISHER)


def _date(value, default):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def _filters(request, allowed):
    today = timezone.localdate()
    start = _date(request.GET.get("from"), today - timedelta(days=90))
    end = _date(request.GET.get("to"), today)
    if end < start:
        start, end = end, start
    dept = request.GET.get("department", "")
    dept_ids = list(allowed)
    if dept.isdigit() and int(dept) in allowed:
        dept_ids = [int(dept)]
    elif dept:
        dept = ""  # an unauthorised or unknown department is ignored, never widened
    state = request.GET.get("state", "")[:20]
    return {"start": start, "end": end, "department": dept, "dept_ids": dept_ids, "state": state}


def _requests(f):
    from demand.models import ResourceRequest

    rows = ResourceRequest.objects.filter(department_id__in=f["dept_ids"], created_at__date__gte=f["start"],
                                          created_at__date__lte=f["end"]).select_related("department", "requester")
    if f["state"] in ResourceRequest.State.values:
        rows = rows.filter(state=f["state"])
    return rows.order_by("-created_at")


def _transfers(f):
    from exchange.models import Consignment

    rows = (Consignment.objects
            .filter(Q(reservation__listing__department_id__in=f["dept_ids"]) | Q(reservation__request__department_id__in=f["dept_ids"]),
                    dispatched_at__date__gte=f["start"], dispatched_at__date__lte=f["end"])
            .select_related("reservation__listing__department", "reservation__request__department", "destination")
            .annotate(accepted=Sum("receipts__quantity")).order_by("-dispatched_at").distinct())
    out = []
    for c in rows:
        accepted = c.accepted or Decimal(0)
        resolved = c.resolutions.aggregate(t=Sum("quantity"))["t"] or Decimal(0)
        status = "Completed" if accepted + resolved >= c.quantity else ("Partially received" if accepted else "In transit")
        if f["state"] in ("Completed", "Partially received", "In transit") and status != f["state"]:
            continue
        out.append({"pk": c.pk, "date": c.dispatched_at, "item": c.reservation.listing.title,
                    "source": c.reservation.listing.department.name, "destination": c.reservation.request.department.name,
                    "location": str(c.destination), "dispatched": c.quantity, "accepted": accepted,
                    "returned_or_lost": resolved, "status": status})
    return out


@active_role_required
def index(request):
    allowed = scope_departments(request.user)
    if allowed is None:
        return permission_denied_response(request, "Reports are available to department representatives and oversight roles.")
    from demand.models import ResourceRequest

    tab = "transfers" if request.GET.get("tab") == "transfers" else "requests"
    f = _filters(request, allowed)
    reqs = list(_requests(f)) if tab == "requests" else []
    transfers = _transfers(f) if tab == "transfers" else []
    totals = {
        "requested": sum((r.quantity for r in reqs), Decimal(0)),
        "dispatched": sum((t["dispatched"] for t in transfers), Decimal(0)),
        "accepted": sum((t["accepted"] for t in transfers), Decimal(0)),
    }
    from core import charts

    all_reqs = list(_requests({**f, "state": ""}))
    all_transfers = _transfers({**f, "state": ""})
    months = charts.monthly_buckets(6)
    req_m = [sum(1 for r in all_reqs if (r.created_at.year, r.created_at.month) == (y, m)) for y, m, _ in months]
    units_m = [float(sum(t["accepted"] for t in all_transfers if (t["date"].year, t["date"].month) == (y, m)))
               for y, m, _ in months]
    labels = [lbl for _, _, lbl in months]
    by_state = {}
    for r in all_reqs:
        by_state[r.get_state_display()] = by_state.get(r.get_state_display(), 0) + 1
    peak = max(by_state.values(), default=1)
    summary = {
        "requests": len(all_reqs), "transfers": len(all_transfers),
        "units": charts.fmt(sum(t["accepted"] for t in all_transfers)),
        "open": sum(1 for r in all_reqs if r.state in ("SUBMITTED", "APPROVED", "PARTIAL")),
        "chart": charts.bar_chart(labels, [("Requests", req_m), ("Units accepted", units_m)]),
        "legend": charts.legend(["Requests", "Units accepted"]),
        "states": [{"name": k, "value": v, "pct": round(100 * v / peak)} for k, v in sorted(by_state.items(), key=lambda kv: -kv[1])],
    }
    query = request.GET.copy()
    query.pop("tab", None)
    snapshots = ReportSnapshot.objects.filter(Q(department__isnull=True) | Q(department_id__in=allowed))
    if not (AccessPolicy.role_codes(request.user) & CAMPUS_ROLES):
        snapshots = snapshots.filter(department_id__in=allowed)
    return render(request, "reporting/index.html", {
        "tab": tab, "f": f, "rows": reqs, "transfers": transfers, "totals": totals,
        "departments": Department.objects.filter(pk__in=allowed),
        "request_states": ResourceRequest.State.choices, "query": query.urlencode(),
        "snapshots": snapshots.order_by("-created_at")[:10], "can_publish": can_publish(request.user), "summary": summary,
        "nav_current": "reports",
    })


@active_role_required
def export(request):
    allowed = scope_departments(request.user)
    if allowed is None:
        return permission_denied_response(request)
    tab = "transfers" if request.GET.get("tab") == "transfers" else "requests"
    f = _filters(request, allowed)
    buffer = io.StringIO()
    out = csv.writer(buffer)
    scope = ", ".join(Department.objects.filter(pk__in=f["dept_ids"]).values_list("name", flat=True))
    out.writerow(safe_row(["UNIventory report", tab.capitalize()]))
    out.writerow(safe_row(["Generated", timezone.localtime().strftime("%Y-%m-%d %H:%M %Z")]))
    out.writerow(safe_row(["Period", f"{f['start']} to {f['end']}"]))
    out.writerow(safe_row(["Departments", scope]))
    out.writerow(safe_row(["Status filter", f["state"] or "All"]))
    out.writerow([])
    if tab == "requests":
        out.writerow(["Request ID", "Title", "Department", "Requester", "Quantity (units)", "Accepted (units)",
                      "Status", "Urgent", "Created", "Needed by"])
        for r in _requests(f):
            out.writerow(safe_row([r.pk, r.title, r.department.name, r.requester.display_name, r.quantity,
                                   r.accepted_quantity, r.get_state_display(), "Yes" if r.urgent else "No",
                                   r.created_at.date(), r.needed_by or ""]))
    else:
        out.writerow(["Consignment ID", "Dispatched", "Item", "From", "To", "Destination", "Dispatched (units)",
                      "Accepted (units)", "Returned or lost (units)", "Status"])
        for t in _transfers(f):
            out.writerow(safe_row([t["pk"], t["date"].date(), t["item"], t["source"], t["destination"], t["location"],
                                   t["dispatched"], t["accepted"], t["returned_or_lost"], t["status"]]))
    _audit_export(request.user, tab, f)
    response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="univentory-{tab}-{f["start"]}-{f["end"]}.csv"'
    return response


class ReportExport:
    """Audit target for an export (FR-54: exports are logged)."""

    def __init__(self, name):
        self.pk = name


def _audit_export(user, tab, f):
    from core.contracts.audit import audit

    audit("report.export", ReportExport(tab), user, after={"report": tab, "from": str(f["start"]), "to": str(f["end"]),
                                                          "departments": f["dept_ids"]})


# ---------------------------------------------------------------------------
# Snapshots and narratives
# ---------------------------------------------------------------------------
def _visible_snapshot(user, pk):
    allowed = scope_departments(user)
    if allowed is None:
        raise Http404
    snap = get_object_or_404(ReportSnapshot, pk=pk)
    campus = bool(AccessPolicy.role_codes(user) & CAMPUS_ROLES)
    if snap.department_id is None and not campus:
        raise Http404
    if snap.department_id is not None and snap.department_id not in allowed:
        raise Http404
    if snap.status != ReportSnapshot.Status.PUBLISHED and not (can_publish(user) or snap.created_by_id == user.pk):
        raise Http404
    return snap


def _draft_narrative(d):
    return (
        f"Between {d['period_start']} and {d['period_end']}, departments recorded {d['requests']} resource requests "
        f"for {d['requested_units']} units. {d['fulfilled']} requests were fully met and {d['open']} remain open.\n\n"
        f"{d['consignments']} consignments moved {d['dispatched_units']} units between departments; receivers accepted "
        f"{d['accepted_units']} units so far. Every accepted unit is a reuse that did not need a new purchase.\n\n"
        f"Procurement validated avoided purchases worth AED {d['avoided_aed']}, and net savings after transfer and repair "
        f"costs are AED {d['savings_aed']}. Of {d['closed_repairs']} closed repair jobs, {d['successful_repairs']} "
        f"returned the item to use.\n\n"
        "Suggested action (not a recorded event): review open requests older than 30 days with the department "
        "representatives, and keep surplus listings current so they can be matched."
    )


@require_POST
@active_role_required
def snapshot_create(request):
    allowed = scope_departments(request.user)
    if allowed is None or not can_publish(request.user):
        return permission_denied_response(request, "Only a report publisher can create a report draft.")
    from sustainability.services import ImpactCalculator

    f = _filters(request, allowed)
    f["state"] = ""
    reqs = list(_requests(f))
    transfers = _transfers(f)
    impact = ImpactCalculator.calculate_all()
    repair = impact["repair_outcomes"]
    data = {
        "period_start": str(f["start"]), "period_end": str(f["end"]),
        "departments": list(Department.objects.filter(pk__in=f["dept_ids"]).values_list("name", flat=True)),
        "requests": len(reqs), "requested_units": _plain(sum((r.quantity for r in reqs), Decimal(0))),
        "fulfilled": sum(1 for r in reqs if r.state == "FULFILLED"),
        "open": sum(1 for r in reqs if r.state in ("SUBMITTED", "APPROVED", "PARTIAL")),
        "consignments": len(transfers),
        "dispatched_units": _plain(sum((t["dispatched"] for t in transfers), Decimal(0))),
        "accepted_units": _plain(sum((t["accepted"] for t in transfers), Decimal(0))),
        "avoided_aed": f"{impact['avoided_purchases']['baseline_value_aed']:.2f}",
        "savings_aed": f"{impact['financial_savings']['financial_savings_aed']:.2f}",
        "closed_repairs": repair["closed_jobs"], "successful_repairs": repair["successful_jobs"],
        "calculation_version": impact["calculation_version"], "synthetic": True,
    }
    dept = Department.objects.filter(pk=int(f["department"])).first() if f["department"] else None
    try:
        snap = ReportingService.create_snapshot(f"Activity summary {f['start']} to {f['end']}", f["start"], f["end"], data,
                                                user=request.user, department=dept)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("reporting:index")
    snap.narrative_draft = _draft_narrative(data)
    snap.save(update_fields=["narrative_draft"])
    from ai.models import AIRun

    now = timezone.now()
    AIRun.objects.create(user=request.user, task_type=AIRun.TaskType.REPORT, status=AIRun.Status.COMPLETED,
                         prompt_version="rules-1.0", schema_version="1.0", result={"snapshot": snap.pk},
                         source_revisions={"snapshot": snap.pk}, started_at=now, completed_at=now)
    messages.success(request, "Draft created from a saved snapshot. Review the text before publishing.")
    return redirect("reporting:snapshot", pk=snap.pk)


def _plain(value) -> str:
    """Decimal as plain text without exponent (10, not 1E+1)."""
    return format(Decimal(value).normalize(), "f")


NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def unsupported_numbers(text: str, data: dict) -> list[str]:
    """Numbers in the narrative that do not appear in the snapshot (AI-09)."""
    allowed = set()
    for value in data.values():
        for token in NUMBER.findall(str(value)):
            allowed.add(token.replace(",", ""))
            try:
                allowed.add(_plain(token.replace(",", "")))
            except Exception:  # noqa: BLE001
                pass
    allowed.update({"30"})  # the fixed review threshold in the suggested action
    bad = []
    for token in NUMBER.findall(text):
        plain = token.replace(",", "")
        try:
            normal = _plain(plain)
        except Exception:  # noqa: BLE001
            normal = plain
        if plain not in allowed and normal not in allowed:
            bad.append(token)
    return bad


@active_role_required
def snapshot_detail(request, pk):
    snap = _visible_snapshot(request.user, pk)
    problems = []
    if request.method == "POST":
        if not can_publish(request.user):
            return permission_denied_response(request, "Only a report publisher can edit or publish a narrative.")
        if snap.status == ReportSnapshot.Status.PUBLISHED:
            messages.error(request, "Published reports cannot be changed. Create a new draft instead.")
            return redirect("reporting:snapshot", pk=pk)
        text = (request.POST.get("narrative") or "").strip()[:8000]
        problems = unsupported_numbers(text, snap.data_snapshot)
        if not problems:
            snap.narrative_draft = text
            snap.save(update_fields=["narrative_draft"])
            if request.POST.get("action") == "publish":
                try:
                    ReportPublicationService.publish(snap.pk, request.user, text)
                except ValidationError as exc:
                    messages.error(request, "; ".join(exc.messages))
                    return redirect("reporting:snapshot", pk=pk)
                messages.success(request, "Report published. Its text and figures are now fixed.")
            else:
                messages.success(request, "Draft saved.")
            return redirect("reporting:snapshot", pk=pk)
        snap.narrative_draft = text
    return render(request, "reporting/snapshot.html", {"snap": snap, "problems": problems,
                                                       "can_publish": can_publish(request.user), "nav_current": "reports"})


@active_role_required
def export_report_csv(request, snapshot_id):
    snap = _visible_snapshot(request.user, snapshot_id)
    buffer = io.StringIO()
    out = csv.writer(buffer)
    out.writerow(safe_row(["Report", snap.title]))
    out.writerow(safe_row(["Status", snap.get_status_display()]))
    out.writerow(safe_row(["Period", f"{snap.period_start} to {snap.period_end}"]))
    out.writerow(safe_row(["Department", snap.department.name if snap.department else "All permitted"]))
    out.writerow([])
    out.writerow(["Measure", "Value"])
    for key, value in snap.data_snapshot.items():
        out.writerow(safe_row([key.replace("_", " "), value]))
    response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="report_{snap.pk}.csv"'
    return response
