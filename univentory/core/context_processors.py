from django.conf import settings

from core.contracts import get_adapter
from core.navigation import entries_for


def shell(request):
    """Values every page in the shared base template needs."""
    user = getattr(request, "user", None)
    nav = []
    current = ""
    if user is not None and user.is_authenticated and getattr(request, "actor_grants", None):
        nav = entries_for(user)
        path = request.path
        matches = [item for item in nav if path.startswith(item["url"]) and item["url"] != "/"]
        if matches:
            current = max(matches, key=lambda item: len(item["url"]))["key"]
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
    }
