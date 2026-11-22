from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from catalogue.services import CatalogueQueryService
from core.contracts import DomainError
from core.web import active_role_required, domain_error_response
from identity.models import Role
from identity.policy import AccessPolicy
from .forms import RequestForm
from .models import ResourceRequest
from .services import DemandService
import uuid


@active_role_required
def request_list(request):
    items = ResourceRequest.objects.filter(requester=request.user, department_id__in=AccessPolicy.departments_with_role(request.user, Role.REQUESTER)).select_related("department")
    return render(request, "demand/list.html", {"items": items, "nav_current": "requests"})


@active_role_required
def request_detail(request, pk):
    item = get_object_or_404(ResourceRequest.objects.select_related("department", "listing"), pk=pk, requester=request.user, department_id__in=AccessPolicy.departments_with_role(request.user, Role.REQUESTER))
    return render(request, "demand/detail.html", {"item": item, "nav_current": "requests"})


@active_role_required
def request_form(request, pk=None, listing_id=None):
    item = get_object_or_404(ResourceRequest, pk=pk, requester=request.user, department_id__in=AccessPolicy.departments_with_role(request.user, Role.REQUESTER), state__in=[ResourceRequest.State.DRAFT, ResourceRequest.State.RETURNED]) if pk else None
    listing = None
    if listing_id:
        try:
            listing = CatalogueQueryService.get_visible(request.user, listing_id)
        except DomainError as exc:
            return domain_error_response(request, exc)
    initial = {"version": item.version} if item else (
        {"title": listing.title, "category": listing.asset.category_id} if listing else {})
    initial["operation_key"] = uuid.uuid4().hex
    form = RequestForm(request.POST or None, instance=item, initial=initial, user=request.user,
                       submitting=request.POST.get("action") == "submit")
    if request.method == "POST" and form.is_valid():
        try:
            saved = DemandService.save(request.user, form.cleaned_data, request_id=pk,
                                       expected_version=form.cleaned_data.get("version"), listing=listing,
                                       submit=request.POST.get("action") == "submit", operation_key=form.cleaned_data["operation_key"])
        except DomainError as exc:
            return domain_error_response(request, exc, "demand/form.html", {"form": form, "item": item, "listing": listing})
        messages.success(request, "Request submitted for approval." if saved.state == saved.State.SUBMITTED else "Draft saved.")
        return redirect("demand:detail", pk=saved.pk)
    return render(request, "demand/form.html", {"form": form, "item": item, "listing": listing, "nav_current": "requests"})


@require_POST
@active_role_required
def cancel(request, pk):
    get_object_or_404(ResourceRequest, pk=pk, requester=request.user)
    try:
        version = int(request.POST.get("version", ""))
    except ValueError:
        return render(request, "core/error.html", {"status": 400, "message": "Invalid request version."}, status=400)
    try:
        DemandService.cancel(request.user, pk, version)
    except DomainError as exc:
        return domain_error_response(request, exc)
    messages.success(request, "Request cancelled.")
    return redirect("demand:detail", pk=pk)
