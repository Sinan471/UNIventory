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
    if not request.user.is_authenticated:
        return redirect("identity:login")
    if not AccessPolicy.has_any_role(request.user):
        return render(request, "core/no_access.html", status=403)
    return redirect(_first_screen(request.user))


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
