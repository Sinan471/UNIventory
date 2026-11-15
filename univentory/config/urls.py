"""Root routing and module composition (Section 8).

Jesher registers each module's namespaced routes here. Sinan's and Jessica's
modules expose ``<module>/urls.py``; they are mounted automatically when the
package is installed, so no member edits another member's routing.
"""
from importlib import util

from django.conf import settings
from django.urls import include, path
from django.views.i18n import set_language

urlpatterns = [
    path("", include("core.urls")),
    path("identity/", include("identity.urls")),
    path("inventory/", include("inventory.urls")),
    path("exchange/", include("catalogue.urls")),
    path("i18n/setlang/", set_language, name="set_language"),
]

for module in settings.OPTIONAL_MODULES:
    if module in settings.INSTALLED_APPS and util.find_spec(f"{module}.urls"):
        urlpatterns.append(path(f"{module.replace('_', '-')}/", include(f"{module}.urls")))

handler403 = "core.views.permission_denied"
handler404 = "core.views.not_found"
handler500 = "core.views.server_error"
