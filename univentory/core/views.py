from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.cache import never_cache

from core.web import active_role_required
from identity.models import Role
from identity.policy import AccessPolicy
from inventory.models import Condition, Lifecycle, SafetyState


def _first_screen(user) -> str:
    """Useful first screen per role (plan Section 13, Visual Standards)."""
    codes = AccessPolicy.role_codes(user)
    candidates = []
    if Role.CUSTODIAN in codes:
        candidates.append("inventory:my_assets")
    if Role.DEPT_REP in codes or Role.APPROVER in codes:
        candidates.extend(["workflow:queue", "catalogue:release_queue"])
    if codes - {Role.SYSADMIN}:
        candidates.append("catalogue:exchange")
    if Role.SYSADMIN in codes:
        candidates.append("identity:admin_home")
    for name in candidates:
        try:
            return reverse(name)
        except NoReverseMatch:
            continue
    return reverse("catalogue:exchange")


def home(request):
    """Workbench: stat tiles, charts and the items waiting on this person."""
    if not request.user.is_authenticated:
        return redirect("identity:login")
    if not AccessPolicy.has_any_role(request.user):
        return render(request, "core/no_access.html", status=403)
    from django.apps import apps
    from django.db.models import Sum

    from catalogue.services import CatalogueQueryService
    from core import charts
    from core.context_processors import _workbench

    user = request.user
    tasks = _workbench(request)
    waiting = [t for t in tasks if t.count]
    cards = [dict(item, task=t.title, action=t.action, icon=t.icon) for t in waiting for item in t.items][:6]
    visible = CatalogueQueryService.search(user, {"availability": "available", "sort": "newest"})         if AccessPolicy.can_browse_catalogue(user) else []
    recent = list(visible[:6]) if visible else []

    months, requests_m, received_m, listed_m = [], [], [], []
    if apps.is_installed("exchange"):
        from demand.models import ResourceRequest
        from exchange.models import ReceiptEvent

        months, requests_m = charts.count_by_month(ResourceRequest.objects.exclude(state="DRAFT"), "created_at")
        _, received_m = charts.count_by_month(ReceiptEvent.objects.all(), "created_at", sum_field="quantity")
    from catalogue.models import Listing

    _, listed_m = charts.count_by_month(Listing.objects.all(), "created_at")
    reused = sum(received_m) if received_m else 0

    by_category = {}
    for listing in (visible or []):
        name = listing.asset.category.name
        by_category[name] = by_category.get(name, 0) + float(listing.free_qty)
    top = sorted(by_category.items(), key=lambda kv: -kv[1])[:6]
    peak = max([v for _, v in top], default=1) or 1

    from sustainability.apps import can_view_impact
    fourth = None
    if apps.is_installed("sustainability") and can_view_impact(user):
        from sustainability.models import AvoidedPurchase

        _, avoided_m = charts.count_by_month(AvoidedPurchase.objects.filter(is_procurement_validated=True),
                                             "recorded_at", sum_field="baseline_value_aed")
        total = AvoidedPurchase.objects.filter(is_procurement_validated=True).aggregate(t=Sum("baseline_value_aed"))["t"] or 0
        fourth = {"label": "Avoided purchases", "value": charts.fmt(total), "unit": "AED", "icon": "coins", "tone": 4,
                  "spark": charts.sparkline(avoided_m), "foot": "Procurement-validated", "url": "sustainability:impact"}
    elif AccessPolicy.departments_with_role(user, Role.REQUESTER):
        from demand.models import ResourceRequest

        mine = ResourceRequest.objects.filter(requester=user).exclude(state__in=["CANCELLED", "REJECTED", "FULFILLED"])
        fourth = {"label": "My open requests", "value": mine.count(), "unit": "", "icon": "clipboard", "tone": 4,
                  "spark": None, "foot": "Draft, awaiting or in progress", "url": "demand:list"}
    elif AccessPolicy.departments_with_role(user, Role.CUSTODIAN):
        from inventory.models import Asset

        count = Asset.objects.filter(custodian=user).count()
        fourth = {"label": "Items you look after", "value": count, "unit": "", "icon": "box", "tone": 4,
                  "spark": None, "foot": "Across your departments", "url": "inventory:my_assets"}

    return render(request, "core/home.html", {
        "waiting": waiting, "tasks": tasks, "cards": cards, "recent": recent, "nav_current": "home",
        "waiting_total": sum(t.count for t in waiting),
        "listed_now": len(visible) if visible else 0, "listed_spark": charts.sparkline(listed_m),
        "reused": charts.fmt(reused), "reused_spark": charts.sparkline(received_m), "fourth": fourth,
        "activity": charts.bar_chart(months, [("Requests", requests_m), ("Units received", received_m)]),
        "activity_legend": charts.legend(["Requests", "Units received"], [sum(requests_m), sum(received_m)]),
        "activity_table": charts.table(["Month", "Requests", "Units received"], list(zip(months, requests_m, received_m))),
        "categories": [{"name": n, "value": v, "pct": round(100 * v / peak)} for n, v in top],
    })


@active_role_required
def design_reference(request):
    """Shared component reference page (S5)."""
    return render(request, "core/design_reference.html", {
        "conditions": Condition, "lifecycles": Lifecycle, "safety": SafetyState,
    })


@never_cache
def healthz(request):
    """Service health metadata only; no business data (plan 7.4)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "unavailable"
    status = 200 if db == "ok" else 503
    return JsonResponse({"status": "ok" if status == 200 else "degraded", "database": db}, status=status)


def permission_denied(request, exception=None):
    return render(request, "core/error.html", {"status": 403}, status=403)


def not_found(request, exception=None):
    return render(request, "core/error.html", {"status": 404}, status=404)


def server_error(request):
    return render(request, "core/error.html", {"status": 500}, status=500)


def csrf_failure(request, reason=""):
    return render(request, "core/error.html", {
        "status": 403,
        "message": "Your form expired or was submitted from another site. Reload the page and try again.",
    }, status=403)
