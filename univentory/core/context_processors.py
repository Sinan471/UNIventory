from django.conf import settings

from core.contracts import get_adapter
from core.navigation import entries_for


def _workbench(request):
    """Compute the signed-in person's tasks once per request."""
    cached = getattr(request, "_univentory_tasks", None)
    if cached is None:
        from core.workbench import tasks_for

        cached = tasks_for(request.user)
        request._univentory_tasks = cached
    return cached


def shell(request):
    """Values every page in the shared base template needs."""
    user = getattr(request, "user", None)
    nav = []
    current = ""
    unread = 0
    role_labels = []
    if user is not None and user.is_authenticated and getattr(request, "actor_grants", None):
        from core.workbench import nav_counts, unread_notifications
        from identity.models import Department, Role

        nav = entries_for(user)
        counts = nav_counts(_workbench(request))
        for item in nav:
            item["count"] = counts.get(item["key"], 0)
        path = request.path
        matches = [item for item in nav if path.startswith(item["url"]) and item["url"] != "/"]
        if matches:
            current = max(matches, key=lambda item: len(item["url"]))["key"]
        elif path == "/":
            current = "home"
        unread = unread_notifications(user)
        names = dict(Role.objects.values_list("code", "name"))
        depts = dict(Department.objects.values_list("pk", "code"))
        grouped: dict[str, list] = {}
        for grant in request.actor_grants:
            scope = grouped.setdefault(names.get(grant.role, grant.role), [])
            if grant.department_id and depts.get(grant.department_id) not in scope:
                scope.append(depts.get(grant.department_id))
        role_labels = [f"{role} ({', '.join(scope)})" if scope else role for role, scope in grouped.items()]
    test_adapters = [
        name
        for name in settings.UNIVENTORY_CONTRACT_ADAPTERS
        if getattr(get_adapter(name), "is_test_adapter", False)
    ]
    return {
        "nav_items": nav,
        "nav_current": current,
        "dev_login_enabled": settings.UNIVENTORY_DEV_LOGIN,
        "test_adapters_active": test_adapters,
        "actor_roles": getattr(request, "actor_role_codes", set()),
        "actor_role_labels": role_labels,
        "unread_notifications": unread,
        # Dark is the default theme; the viewer's choice is a cookie (no personal data).
        "ui_theme": "light" if request.COOKIES.get("uv_theme") == "light" else "dark",
    }
