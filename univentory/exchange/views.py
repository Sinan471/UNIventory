import uuid
from django.db.models import Q
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


@active_role_required
def queue(request):
    rows = visible_reservations(request.user).select_related("request", "listing", "listing__department")
    return render(request, "exchange/queue.html", {"rows": rows})


@active_role_required
def reserve(request, pk):
    need = get_object_or_404(ResourceRequest, pk=pk, requester=request.user, department_id__in=AccessPolicy.departments_with_role(request.user, Role.REQUESTER), state__in=[ResourceRequest.State.APPROVED, ResourceRequest.State.PARTIAL])
    if not need.listing_id:
        return render(request, "core/error.html", {"status": 422, "message": "This need has no associated listing. Choose an item before creating a request."}, status=422)
    try:
        listing = CatalogueQueryService.get_visible(request.user, need.listing_id)
    except DomainError as exc:
        return domain_error_response(request, exc)
    form = QuantityForm(request.POST or None, initial={"quantity": need.quantity})
    if request.method == "POST" and form.is_valid():
        try:
            row = ReservationService.request(request.user, need.pk, listing.pk, form.cleaned_data["quantity"])
        except DomainError as exc:
            return domain_error_response(request, exc, "exchange/reserve.html", {"need": need, "listing": listing, "form": form})
        return redirect("transfer:detail", pk=row.pk)
    return render(request, "exchange/reserve.html", {"need": need, "listing": listing, "form": form})


@active_role_required
def detail(request, pk):
    row = get_object_or_404(visible_reservations(request.user).select_related("request", "listing__asset", "listing__department"), pk=pk)
    source_rep = AccessPolicy.has_role(request.user, Role.DEPT_REP, row.listing.department_id) and request.user.pk != row.requested_by_id
    dest_rep = AccessPolicy.has_role(request.user, Role.DEPT_REP, row.request.department_id) and request.user.pk != row.requested_by_id
    can_dispatch = AccessPolicy.can_edit_asset(request.user, row.listing.asset)
    form = DispatchForm(request.POST or None, department=row.request.department)
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
                return render(request, "exchange/detail.html", {"row": row, "form": form, "source_rep": source_rep, "dest_rep": dest_rep, "can_dispatch": can_dispatch, "operation_key": operation_key}, status=422)
        except DomainError as exc:
            return domain_error_response(request, exc, "exchange/detail.html", {"row": row, "form": form, "source_rep": source_rep, "dest_rep": dest_rep, "can_dispatch": can_dispatch, "operation_key": operation_key})
        return redirect("transfer:detail", pk=pk)
    return render(request, "exchange/detail.html", {"row": row, "form": form, "source_rep": source_rep, "dest_rep": dest_rep, "can_dispatch": can_dispatch, "operation_key": operation_key})


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
