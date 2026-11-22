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


# Workflow states from every module, mapped to one tone vocabulary so a
# state reads the same on every page.
STATUS_TONE = {
    # requests
    "SUBMITTED": "attention", "APPROVED": "success", "PARTIAL": "info", "FULFILLED": "success",
    "RETURNED": "attention", "REJECTED": "danger", "CANCELLED": "neutral", "EXPIRED": "neutral",
    # reservations
    "PENDING": "attention", "HELD": "attention", "COMMITTED": "info", "RELEASED": "neutral", "CONSUMED": "success",
    # care
    "INSPECTION": "attention", "AWAITING_APPROVAL": "attention", "IN_PROGRESS": "info", "VERIFY": "attention",
    "CLOSED": "neutral", "SUCCESS": "success", "FAILED": "danger", "NO_REPAIR": "success",
    # final actions
    "PROPOSED": "attention", "COMPLETED": "success",
    # generic
    "DRAFT": "neutral", "PUBLISHED": "success", "pending": "attention", "approved": "success",
    "returned": "attention", "rejected": "danger", "superseded": "neutral",
}


@register.simple_tag
def status_badge(value, label=None):
    """Badge for any workflow state: ``{% status_badge obj.state obj.get_state_display %}``."""
    value = getattr(value, "value", value)
    text = label or str(value).replace("_", " ").capitalize()
    return _badge(STATUS_TONE.get(value, "neutral"), text)


@register.filter
def split(value, sep=" "):
    return str(value).split(sep)


@register.filter
def join_if_list(value):
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return value


@register.filter
def key_label(value):
    return str(value).replace("_", " ").capitalize()


# Item illustrations matched from the title (first keyword wins). Category
# art is the fallback. These are illustrations, never evidence photographs.
ITEM_ART = [
    # Specific words first so "desk organiser" and "EliteDesk" do not read as a desk.
    ("binder", ("binder", "organiser", "stationery", "folder")), ("desktop", ("desktop", "elitedesk", " pc")),
    ("office-chair", ("ergonomic", "office chair", "mesh", "visitor chair")), ("stacking-chair", ("stacking", "seminar chair", "chair")),
    ("whiteboard", ("whiteboard",)), ("laptop", ("laptop", "thinkpad", "latitude", "notebook")),
    ("display", ("interactive display", "65-inch", " tv")), ("monitor", ("monitor", "screen", "display")),
    ("projector", ("projector",)), ("speaker", ("speaker",)), ("camera", ("camera",)), ("microscope", ("microscope",)),
    ("centrifuge", ("centrifuge",)), ("balance", ("balance", "scale")), ("hotplate", ("hotplate", "stirrer")),
    ("drill", ("drill",)), ("goggles", ("goggles", "safety")), ("toolbox", ("workbench", "caliper", "tool")),
    ("paper", ("paper", "ream")), ("cabinet", ("cabinet", "filing", "locker")), ("desk", ("desk", "table", "workstation")),
]


@register.simple_tag
def item_art(obj):
    """Illustration URL for an asset, listing or request (title based)."""
    from django.templatetags.static import static

    text = obj if isinstance(obj, str) else getattr(obj, "title", "")
    title = " " + str(text or "").lower()
    for slug, words in ITEM_ART:
        if any(w in title for w in words):
            return static(f"graphics/items/{slug}.svg")
    asset = getattr(obj, "asset", obj)
    return category_art(getattr(asset, "category", None))


@register.simple_tag
def chart_bar(categories, series, unit=""):
    from core.charts import bar_chart
    return bar_chart(categories, series, unit=unit)


@register.simple_tag
def chart_area(categories, values, unit=""):
    from core.charts import area_chart
    return area_chart(categories, values, unit=unit)


@register.simple_tag
def chart_spark(values):
    from core.charts import sparkline
    return sparkline(values)


@register.simple_tag
def chart_donut(segments, center_value="", center_label=""):
    from core.charts import donut
    return donut(segments, center_value=center_value, center_label=center_label)


@register.simple_tag
def chart_legend(names, values=None, unit=""):
    from core.charts import legend
    return legend(names, values, unit)


@register.filter
def fmt(value):
    from core.charts import fmt as _fmt
    return _fmt(value)


CATEGORY_ITEM = {"IT": "laptop", "FURN": "office-chair", "LAB": "microscope", "AV": "projector",
                 "OFF": "paper", "TOOL": "drill"}


@register.simple_tag
def category_item_art(category):
    """Representative item illustration for a category tile."""
    from django.templatetags.static import static

    slug = CATEGORY_ITEM.get(getattr(category, "code", ""), None)
    return static(f"graphics/items/{slug}.svg") if slug else category_art(category)
