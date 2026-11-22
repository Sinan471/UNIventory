"""Presentation helpers for requests (owner: Sinan's demand module)."""
from decimal import Decimal

from django import template
from django.db.models import Sum

register = template.Library()


@register.simple_tag
def request_progress(item):
    """Stages of one need, from draft to accepted receipt (FR-16).

    Returns ``[(label, status)]`` where status is done, current, stopped or
    todo. Only accepted receipt counts as fulfilment.
    """
    from exchange.models import Consignment, Reservation

    reservations = list(item.reservations.all())
    states = {r.state for r in reservations}
    dispatched = Consignment.objects.filter(reservation__request=item).aggregate(t=Sum("quantity"))["t"] or Decimal(0)
    accepted = item.accepted_quantity
    stages = [
        ("Draft", True),
        ("Submitted", item.state not in ("DRAFT",)),
        ("Need approved", item.state in ("APPROVED", "PARTIAL", "FULFILLED")),
        ("Reservation requested", bool(reservations)),
        ("Stock held", bool(states & {Reservation.State.HELD, Reservation.State.COMMITTED}) or dispatched > 0),
        ("Transfer approved", Reservation.State.COMMITTED in states or dispatched > 0),
        ("Dispatched", dispatched > 0),
        ("Received", accepted > 0),
    ]
    stopped = item.state in ("REJECTED", "CANCELLED", "RETURNED")
    out = []
    last_done = max(i for i, (_, done) in enumerate(stages) if done)
    for i, (label, done) in enumerate(stages):
        if stopped and i == last_done:
            out.append((f"{label} ({item.get_state_display().lower()})", "stopped"))
        elif i < last_done or (done and item.state == "FULFILLED"):
            out.append((label, "done"))
        elif i == last_done:
            out.append((label, "current"))
        else:
            out.append((label, "todo"))
    return out


@register.simple_tag
def quantity_breakdown(item):
    """Requested, held, dispatched, accepted and outstanding quantities (FR-16)."""
    from exchange.models import Consignment, Reservation

    held = item.reservations.filter(state__in=[Reservation.State.HELD, Reservation.State.COMMITTED]).aggregate(
        t=Sum("quantity"))["t"] or Decimal(0)
    dispatched = Consignment.objects.filter(reservation__request=item).aggregate(t=Sum("quantity"))["t"] or Decimal(0)
    accepted = item.accepted_quantity
    return {"requested": item.quantity, "held": held, "dispatched": dispatched, "accepted": accepted,
            "outstanding": item.quantity - accepted, "in_transit": max(dispatched - accepted, Decimal(0))}
