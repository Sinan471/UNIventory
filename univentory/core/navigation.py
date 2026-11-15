"""Global navigation registry (plan Section 13, Global Navigation).

Jesher owns global navigation and its strings. Each module contributes
entries by calling ``register`` from its ``AppConfig.ready``; an entry is
shown only when its route exists and its ``visible`` predicate allows the
current user. This keeps one navigation rail across all three members'
pages without anyone editing another module's templates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class NavEntry:
    key: str
    label: str
    url_name: str
    icon: str
    order: int
    visible: Callable = field(default=lambda user: True)
    primary_on_mobile: bool = False


_REGISTRY: dict[str, NavEntry] = {}

# Documented destinations in their fixed order. Modules owned by Sinan and
# Jessica register the url_name when their routes exist.
PLANNED = {
    "exchange": (_("Exchange"), "search", 10, True),
    "requests": (_("My Requests"), "clipboard", 20, True),
    "assets": (_("My Assets"), "box", 30, True),
    "approvals": (_("Approvals"), "check-circle", 40, True),
    "care": (_("Care"), "wrench", 50, False),
    "impact": (_("Impact"), "leaf", 60, False),
    "reports": (_("Reports"), "bar-chart", 70, False),
    "admin": (_("Administration"), "settings", 90, False),
}


def register(key: str, url_name: str, visible: Callable | None = None) -> None:
    label, icon, order, primary = PLANNED.get(key, (key.title(), "circle", 80, False))
    _REGISTRY[key] = NavEntry(
        key=key,
        label=label,
        url_name=url_name,
        icon=icon,
        order=order,
        visible=visible or (lambda user: True),
        primary_on_mobile=primary,
    )


def entries_for(user) -> list[dict]:
    items = []
    for entry in sorted(_REGISTRY.values(), key=lambda e: e.order):
        try:
            url = reverse(entry.url_name)
        except NoReverseMatch:
            continue
        if not entry.visible(user):
            continue
        items.append(
            {
                "key": entry.key,
                "label": entry.label,
                "url": url,
                "icon": entry.icon,
                "primary": entry.primary_on_mobile,
            }
        )
    return items
