"""AI widgets mounted in other modules' pages (owner: Jessica's ai module).

Each widget reads through the same scoped services as the ordinary pages and
never changes stock, approvals or records by itself.
"""
from django import template

register = template.Library()

FACTOR_LABELS = [
    ("functional_fit", "Functional fit", 40),
    ("quantity_coverage", "Quantity coverage", 20),
    ("condition", "Condition", 15),
    ("location_timing", "Location and timing", 10),
    ("reuse_cost", "Reuse cost", 10),
    ("environmental_evidence", "Environmental evidence", 5),
]


@register.inclusion_tag("ai/match_panel.html", takes_context=True)
def match_panel(context, need):
    request = context["request"]
    user = request.user
    show = need.requester_id == user.pk and need.state in ("SUBMITTED", "APPROVED", "PARTIAL")
    matches, error = [], ""
    if show:
        from ai.matching import MatchingService

        try:
            matches = MatchingService.for_request(user, need)
        except Exception:  # noqa: BLE001 - AI-18: fall back to the manual path
            error = "Suggestions are unavailable right now. Search the exchange instead."
        for m in matches:
            m["factor_rows"] = [
                {"label": label, "weight": weight,
                 "value": None if m["factors"].get(key) is None else round(m["factors"][key] * 100)}
                for key, label, weight in FACTOR_LABELS
            ]
    return {"show": show, "need": need, "matches": matches, "error": error,
            "can_reserve": need.state in ("APPROVED", "PARTIAL"), "csrf_token": context.get("csrf_token")}


@register.inclusion_tag("ai/advice_panel.html", takes_context=True)
def advice_panel(context, asset):
    """Next-action advice for the custodian or department representative (AI-07)."""
    from identity.policy import AccessPolicy

    user = context["request"].user
    portion = asset.portions.filter(is_active_leaf=True).order_by("pk").first()
    if portion is None or not AccessPolicy.can_view_asset_record(user, asset):
        return {"show": False}
    from demand.models import ResourceRequest

    from ai.advice import assess

    demand = ResourceRequest.objects.filter(category_id=asset.category_id,
                                            state__in=["SUBMITTED", "APPROVED", "PARTIAL"]).count()
    result = assess(portion, demand)
    tone = {"suggested": "success", "possible": "info", "not needed": "neutral", "blocked": "danger",
            "needs evidence": "attention", "last resort": "attention"}
    for row in result["rows"]:
        row["tone"] = tone.get(row["verdict"], "neutral")
    return {"show": True, "advice": result, "asset": asset, "portion": portion,
            "can_act": AccessPolicy.can_edit_asset(user, asset)}
