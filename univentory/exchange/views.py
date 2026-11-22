import uuid
from django.db.models import Q
from decimal import Decimal
from django.shortcuts import get_object_or_404, redirect, render
from catalogue.services import CatalogueQueryService
from core.contracts import DomainError
from core.web import active_role_required, domain_error_response
from demand.models import ResourceRequest
from identity.models import Role
from identity.policy import AccessPolicy
from .forms import DispatchForm, QuantityForm, ResolutionForm
from .models import Consignment, Reservation
from .services import ReservationService, TransferService


def visible_reservations(user):
    reps = AccessPolicy.departments_with_role(user, Role.DEPT_REP)
    requester_depts = AccessPolicy.departments_with_role(user, Role.REQUESTER)
    custodians = AccessPolicy.departments_with_role(user, Role.CUSTODIAN)
    receivers = AccessPolicy.departments_with_role(user, Role.RECEIVER)
    return Reservation.objects.filter(Q(request__requester=user, request__department_id__in=requester_depts) | Q(listing__department_id__in=reps) |
        Q(request__department_id__in=reps) | Q(listing__asset__custodian=user, listing__department_id__in=custodians) | Q(consignments__receiver=user, request__department_id__in=receivers)).distinct()


NEXT_STEP = {
    Reservation.State.PENDING: "Owning department approves the hold",
    Reservation.State.HELD: "Receiving department approves the transfer",
    Reservation.State.COMMITTED: "Custodian dispatches; receiver confirms",
}


def _your_action(user, row):
    """The step this person can take now, using the same checks as the services."""
    from django.db.models import Sum

    if row.requested_by_id != user.pk:
        if row.state == Reservation.State.PENDING and AccessPolicy.has_role(user, Role.DEPT_REP, row.listing.department_id):
            return "holds", "Approve or reject hold"
        if row.state == Reservation.State.HELD and AccessPolicy.has_role(user, Role.DEPT_REP, row.request.department_id):
            return "transfers", "Approve transfer"
    if row.state == Reservation.State.COMMITTED and AccessPolicy.can_edit_asset(user, row.listing.asset):
        sent = row.consignments.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        if sent < row.quantity:
            return "dispatch", "Dispatch"
    for shipment in row.consignments.all():
        if shipment.receiver_id == user.pk:
            done = (shipment.receipts.aggregate(t=Sum("quantity"))["t"] or Decimal(0)) + (
                shipment.resolutions.aggregate(t=Sum("quantity"))["t"] or Decimal(0))
            if done < shipment.quantity:
                return "receive", "Confirm receipt"
    return "", ""


@active_role_required
def queue(request):
    rows = list(visible_reservations(request.user).select_related(
        "request", "request__department", "listing", "listing__department", "listing__asset").order_by("-created_at"))
    show = request.GET.get("show", "")
    mine, others = [], []
    from django.db.models import Sum
    for row in rows:
        row.action_key, row.action_label = _your_action(request.user, row)
        row.next_step = NEXT_STEP.get(row.state, "")
        row.status_value, row.status_label = row.state, row.get_state_display()
        if row.state == Reservation.State.COMMITTED:
            sent = row.consignments.aggregate(t=Sum("quantity"))["t"] or Decimal(0)
            done = sum(((c.receipts.aggregate(t=Sum("quantity"))["t"] or Decimal(0))
                        + (c.resolutions.aggregate(t=Sum("quantity"))["t"] or Decimal(0))) for c in row.consignments.all())
            if sent >= row.quantity and done >= row.quantity:
                row.status_value, row.status_label, row.next_step = "COMPLETED", "Completed", ""
            elif sent > 0:
                row.status_value, row.status_label = "IN_PROGRESS", "In transit"
                row.next_step = "Receiver confirms" if sent >= row.quantity else "Custodian dispatches the rest"
        (mine if row.action_key and (not show or row.action_key == show) else others).append(row)
    return render(request, "exchange/queue.html", {"mine": mine, "others": others, "show": show, "nav_current": "transfers"})


@active_role_required
def reserve(request, pk):
    need = get_object_or_404(ResourceRequest, pk=pk, requester=request.user, department_id__in=AccessPolicy.departments_with_role(request.user, Role.REQUESTER), state__in=[ResourceRequest.State.APPROVED, ResourceRequest.State.PARTIAL])
    # A suggested match (ai:match_decide) may name the listing; it is rechecked here.
    listing_id = request.GET.get("listing", "")
    listing_id = int(listing_id) if listing_id.isdigit() else need.listing_id
    if not listing_id:
        return render(request, "core/error.html", {"status": 422, "message": "This need has no associated listing. Choose an item from the suggestions or the exchange first."}, status=422)
    try:
        listing = CatalogueQueryService.get_visible(request.user, listing_id)
    except DomainError as exc:
        return domain_error_response(request, exc)
    form = QuantityForm(request.POST or None, initial={"quantity": need.quantity})
    if request.method == "POST" and form.is_valid():
        try:
            row = ReservationService.request(request.user, need.pk, listing.pk, form.cleaned_data["quantity"])
        except DomainError as exc:
            return domain_error_response(request, exc, "exchange/reserve.html", {"need": need, "listing": listing, "form": form})
        return redirect("transfer:detail", pk=row.pk)
    return render(request, "exchange/reserve.html", {"need": need, "listing": listing, "form": form, "nav_current": "requests"})


@active_role_required
def detail(request, pk):
    row = get_object_or_404(visible_reservations(request.user).select_related("request", "listing__asset", "listing__department"), pk=pk)
    source_rep = AccessPolicy.has_role(request.user, Role.DEPT_REP, row.listing.department_id) and request.user.pk != row.requested_by_id
    dest_rep = AccessPolicy.has_role(request.user, Role.DEPT_REP, row.request.department_id) and request.user.pk != row.requested_by_id
    can_dispatch = AccessPolicy.has_role(request.user, Role.CUSTODIAN, row.listing.department_id) and AccessPolicy.can_edit_asset(request.user, row.listing.asset)
    can_resolve = can_dispatch or source_rep
    shipments = list(row.consignments.select_related("destination", "receiver").prefetch_related("receipts", "resolutions"))
    dispatched = sum((shipment.quantity for shipment in shipments), Decimal(0))
    for shipment in shipments:
        shipment.received_quantity = sum((event.quantity for event in shipment.receipts.all()), Decimal(0))
        shipment.resolved_quantity = sum((event.quantity for event in shipment.resolutions.all()), Decimal(0))
        shipment.remaining_quantity = shipment.quantity - shipment.received_quantity - shipment.resolved_quantity
    can_dispatch = can_dispatch and dispatched < row.quantity
    status_value, status_label = row.state, row.get_state_display()
    if row.state == Reservation.State.COMMITTED and dispatched > 0:
        settled = all(s.remaining_quantity <= 0 for s in shipments) and dispatched >= row.quantity
        status_value, status_label = ("COMPLETED", "Completed") if settled else ("IN_PROGRESS", "In transit")
    context = {"status_value": status_value, "status_label": status_label,"row": row, "source_rep": source_rep, "dest_rep": dest_rep, "can_dispatch": can_dispatch,
               "can_resolve": can_resolve, "shipments": shipments, "dispatched": dispatched, "undispatched": row.quantity - dispatched}
    form = DispatchForm(request.POST or None, department=row.request.department,
                        initial={"quantity": row.quantity, "destination": row.request.destination_id})
    operation_key = request.POST.get("operation_key", "") if request.method == "POST" else uuid.uuid4().hex
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action in ("hold", "commit", "reject", "cancel"):
                try:
                    version = int(request.POST.get("version", ""))
                except ValueError:
                    return render(request, "core/error.html", {"status": 400}, status=400)
                if action == "hold":
                    ReservationService.approve(request.user, pk, version)
                elif action == "commit":
                    ReservationService.commit(request.user, pk, version)
                elif action == "reject":
                    ReservationService.reject(request.user, pk, version, request.POST.get("reason", ""))
                else:
                    ReservationService.cancel(request.user, pk, version, request.POST.get("reason", ""))
            elif action == "dispatch" and form.is_valid():
                TransferService.dispatch(request.user, pk, operation_key=operation_key, **form.cleaned_data)
            else:
                return render(request, "exchange/detail.html", {**context, "form": form, "operation_key": operation_key}, status=422)
        except DomainError as exc:
            return domain_error_response(request, exc, "exchange/detail.html", {**context, "form": form, "operation_key": operation_key})
        return redirect("transfer:detail", pk=pk)
    return render(request, "exchange/detail.html", {**context, "form": form, "operation_key": operation_key, "nav_current": "transfers"})


@active_role_required
def receipt(request, pk):
    row = get_object_or_404(Consignment.objects.select_related("reservation"), pk=pk, receiver=request.user,
        reservation__request__department_id__in=AccessPolicy.departments_with_role(request.user, Role.RECEIVER))
    form = QuantityForm(request.POST or None)
    key = request.POST.get("operation_key") if request.method == "POST" else uuid.uuid4().hex
    if request.method == "POST" and form.is_valid():
        try:
            TransferService.receive(request.user, pk, form.cleaned_data["quantity"], key)
        except DomainError as exc:
            return domain_error_response(request, exc, "exchange/receipt.html", {"consignment": row, "form": form, "operation_key": key})
        return redirect("transfer:detail", pk=row.reservation_id)
    return render(request, "exchange/receipt.html", {"consignment": row, "form": form, "operation_key": key})


@active_role_required
def resolve(request, pk):
    row = get_object_or_404(Consignment.objects.select_related("reservation__listing__asset", "reservation__listing__department"),
                            pk=pk, reservation__in=visible_reservations(request.user))
    listing = row.reservation.listing
    if not (AccessPolicy.can_edit_asset(request.user, listing.asset) or AccessPolicy.has_role(request.user, Role.DEPT_REP, listing.department)):
        return render(request, "core/error.html", {"status": 404}, status=404)
    form = ResolutionForm(request.POST or None, department=listing.department)
    if request.method == "POST" and form.is_valid():
        try:
            TransferService.resolve(request.user, row.pk, **form.cleaned_data)
        except DomainError as exc:
            return domain_error_response(request, exc, "exchange/resolve.html", {"consignment": row, "form": form})
        return redirect("transfer:detail", pk=row.reservation_id)
    return render(request, "exchange/resolve.html", {"consignment": row, "form": form})
