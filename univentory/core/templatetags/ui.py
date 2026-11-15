"""Shared presentation helpers (owner: Jesher).

State badges always pair text with colour and an indicator, never colour
alone (plan Section 15, UI Quality Gate).
"""
from decimal import Decimal

from django import template
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext as _

register = template.Library()

LIFECYCLE_TONE = {
    "DRAFT": "neutral", "IN_USE": "info", "AVAILABLE": "success", "UNDER_INSPECTION": "attention",
    "UNDER_MAINTENANCE": "attention", "IN_TRANSIT": "info", "RETIRED": "neutral", "DONATED": "neutral",
    "RECOVERED": "neutral", "RECYCLED": "neutral", "DISPOSED": "neutral", "LOST": "danger",
}
LISTING_TONE = {
    "DRAFT": "neutral", "AWAITING_RELEASE": "attention", "PUBLISHED": "success", "PAUSED": "attention",
    "WITHDRAWN": "neutral", "CLOSED": "neutral",
}
SAFETY_TONE = {"UNKNOWN": "attention", "CLEARED": "success", "RESTRICTED": "danger"}
CONDITION_TONE = {"UNKNOWN": "neutral", "POOR": "danger", "FAIR": "attention", "GOOD": "success", "EXCELLENT": "success"}
ALLOCATION_TONE = {"FREE": "neutral", "HELD": "attention", "COMMITTED": "info", "FINAL_COMMITTED": "info",
                   "SETTLED": "neutral"}


def _badge(tone: str, label: str, title: str = ""):
    return format_html('<span class="badge badge-{}"{}>{}</span>', tone,
                       format_html(' title="{}"', title) if title else "", label)


@register.simple_tag
def lifecycle_badge(obj_or_value, label=None):
    value = getattr(obj_or_value, "value", obj_or_value)
    text = label or getattr(obj_or_value, "label", None) or str(value).replace("_", " ").title()
    return _badge(LIFECYCLE_TONE.get(value, "neutral"), text)


@register.simple_tag
def listing_badge(listing):
    return _badge(LISTING_TONE.get(listing.state, "neutral"), listing.get_state_display())


@register.simple_tag
def safety_badge(portion):
    return _badge(SAFETY_TONE.get(portion.safety_state, "neutral"), portion.get_safety_state_display(),
                  _("Safety decision"))


@register.simple_tag
def condition_badge(value, label):
    return _badge(CONDITION_TONE.get(value, "neutral"), label, _("Condition"))


@register.simple_tag
def allocation_badge(portion):
    return _badge(ALLOCATION_TONE.get(portion.allocation, "neutral"), portion.get_allocation_display())


@register.simple_tag
def tone_badge(tone, label):
    return _badge(tone, label)


@register.filter
def qty(value, asset=None):
    """Quantities: whole numbers for counted units, trimmed decimals otherwise."""
    if value is None:
        return "-"
    value = Decimal(value)
    if asset is not None and getattr(asset, "unit", "EA") in {"EA", "SET", "BOX"}:
        return f"{int(value):,}"
    text = f"{value.normalize():f}"
    return text


@register.filter
def unit_label(asset):
    """Unit text for measured quantities; counted 'each' units need no label."""
    if asset is None or getattr(asset, "unit", "EA") == "EA":
        return ""
    return asset.get_unit_display()


@register.filter
def aed(value):
    if value is None:
        return _("Unknown")
    return f"AED {Decimal(value):,.2f}"


@register.filter
def initials(user):
    name = (getattr(user, "display_name", "") or getattr(user, "username", "") or "?").split()
    return "".join(part[0] for part in name[:2]).upper()


@register.filter
def pct(part, whole):
    try:
        whole = Decimal(whole)
        return float(Decimal(part) / whole * 100) if whole else 0
    except Exception:  # noqa: BLE001
        return 0


@register.simple_tag
def icon(name, extra_class=""):
    return format_html('<svg class="icon {}" aria-hidden="true" focusable="false"><use href="#i-{}"></use></svg>',
                       extra_class, name)


@register.simple_tag
def category_art(category):
    from django.templatetags.static import static

    slug = getattr(category, "illustration", "office") or "office"
    return static(f"graphics/catalogue/{slug}.svg")


@register.simple_tag
def evidence_url(attachment):
    return reverse("inventory:attachment_download", args=[attachment.pk])


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def split_words(value):
    return str(value).split()
