"""Exchange (catalogue) views. Thin: parse, call a service, render."""
from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from catalogue.forms import CatalogueFilterForm, ListingActionForm, ListingForm, ReleaseDecisionForm
from catalogue.models import Listing, ListingState
from catalogue.services import TRANSITIONS, CatalogueQueryService, CatalogueService
from core.contracts import DomainError, NotPermitted, get_adapter
from core.web import active_role_required, actor_from, domain_error_response, new_operation_key
from identity.policy import AccessPolicy
from inventory.models import Attachment, AttachmentAccess
from inventory.services import AssetQueryService


def _photos(asset, user, *, restricted_ok: bool):
    qs = asset.attachments.filter(withdrawn_at__isnull=True, status="ACCEPTED",
                                  content_type__in=["image/jpeg", "image/png"])
    if not restricted_ok:
        qs = qs.filter(access_class=AttachmentAccess.CATALOGUE_PHOTO)
    return list(qs.order_by("uploaded_at"))


def _request_url(listing) -> str:
    """Sinan's request flow owns the 'Request this item' destination."""
    try:
        return reverse("demand:new_from_listing", args=[listing.pk])
    except NoReverseMatch:
        return ""


@active_role_required
def exchange(request):
    form = CatalogueFilterForm(request.GET or None)
    params = form.params()
    results = CatalogueQueryService.search(request.user, params)
    paginator = Paginator(results, CatalogueQueryService.page_size())
    page = paginator.get_page(request.GET.get("page"))
    # One query for every card's first catalogue photo (no per-card queries).
    asset_ids = [listing.asset_id for listing in page.object_list]
    photo_by_asset = {}
    for attachment in Attachment.objects.filter(
        asset_id__in=asset_ids, withdrawn_at__isnull=True, status="ACCEPTED",
        access_class=AttachmentAccess.CATALOGUE_PHOTO, content_type__in=["image/jpeg", "image/png"],
    ).order_by("uploaded_at"):
        photo_by_asset.setdefault(attachment.asset_id, attachment)
    first_photo = {listing.pk: photo_by_asset.get(listing.asset_id) for listing in page.object_list}
    query = request.GET.copy()
    query.pop("page", None)
    view_mode = request.GET.get("view") if request.GET.get("view") in ("grid", "list") else "grid"
    return render(request, "catalogue/exchange.html", {
        "form": form,
        "page": page,
        "count": paginator.count,
        "photos": first_photo,
        "querystring": query.urlencode(),
        "view_mode": view_mode,
        "active_filters": form.active_filters(),
    })


@active_role_required
def listing_detail(request, pk):
    try:
        listing = CatalogueQueryService.get_visible(request.user, pk)
    except DomainError as exc:
        return domain_error_response(request, exc)
    CatalogueService.sync_release_outcome(listing)
    can_manage = AccessPolicy.can_manage_listing(request.user, listing)
    can_view_record = AccessPolicy.can_view_asset_record(request.user, listing.asset)
    decision = get_adapter("RELEASE_APPROVALS").current_decision(listing=listing) if can_view_record else None
    actions = []
    if can_manage:
        actions = [name for name, (sources, _target) in TRANSITIONS.items() if listing.state in sources]
    return render(request, "catalogue/listing_detail.html", {
        "listing": listing,
        "asset": listing.asset,
        "photos": _photos(listing.asset, request.user, restricted_ok=can_view_record),
        "free_qty": CatalogueService.free_quantity(listing),
        "can_manage": can_manage,
        "can_view_record": can_view_record,
        "decision": decision,
        "actions": actions,
        "blockers": CatalogueService.publication_blockers(listing) if can_manage and listing.state in (
            ListingState.AWAITING_RELEASE, ListingState.DRAFT) else [],
        "action_form": ListingActionForm(initial={"version": listing.version, "operation_key": new_operation_key()}),
        "request_url": _request_url(listing),
        "spec_rows": [
            (field.get("label", field["key"]), listing.asset.specifications.get(field["key"]), field.get("unit", ""))
            for field in listing.asset.category.spec_schema
            if listing.asset.specifications.get(field["key"]) not in (None, "")
        ],
    })


@active_role_required
def listing_new(request, asset_id):
    try:
        asset = AssetQueryService.get_record(request.user, asset_id)
    except DomainError as exc:
        return domain_error_response(request, exc)
    if not AccessPolicy.can_edit_asset(request.user, asset):
        return domain_error_response(request, NotPermitted(_("Only the assigned custodian can list this asset.")))
    releasable = CatalogueService.on_hand_releasable(asset, asset.department_id)
    form = ListingForm(request.POST or None, initial={
        "operation_key": new_operation_key(),
        "title": asset.title,
        "public_description": asset.description,
        "offered_quantity": releasable,
        "collection_info": f"{asset.location.building}, {asset.location.name}",
    })
    ctx = {"form": form, "asset": asset, "releasable": releasable}
    if request.method == "POST":
        if not form.is_valid():
            return render(request, "catalogue/listing_form.html", ctx, status=422)
        try:
            listing = CatalogueService.create(
                actor_from(request), asset=asset, title=form.cleaned_data["title"],
                public_description=form.cleaned_data["public_description"],
                offered_quantity=form.cleaned_data["offered_quantity"],
                collection_info=form.cleaned_data["collection_info"],
            )
        except DomainError as exc:
            _apply_errors(form, exc)
            return domain_error_response(request, exc, "catalogue/listing_form.html", ctx)
        messages.success(request, _("Listing saved as a draft. Submit it for release review when ready."))
        return redirect("catalogue:listing_detail", pk=listing.pk)
    return render(request, "catalogue/listing_form.html", ctx)


@active_role_required
def listing_edit(request, pk):
    listing = get_object_or_404(Listing.objects.select_related("asset"), pk=pk)
    if not AccessPolicy.can_manage_listing(request.user, listing):
        if AccessPolicy.can_view_asset_record(request.user, listing.asset):
            return render(request, "core/error.html", {"status": 403}, status=403)
        return render(request, "core/error.html", {"status": 404}, status=404)
    form = ListingForm(request.POST or None, initial={
        "version": listing.version, "title": listing.title, "public_description": listing.public_description,
        "offered_quantity": listing.offered_quantity, "collection_info": listing.collection_info,
    })
    ctx = {"form": form, "asset": listing.asset, "listing": listing,
           "releasable": CatalogueService.on_hand_releasable(listing.asset, listing.department_id)}
    if request.method == "POST":
        if not form.is_valid():
            return render(request, "catalogue/listing_form.html", ctx, status=422)
        try:
            CatalogueService.update_draft(
                actor_from(request), listing.pk, expected_version=form.cleaned_data["version"] or 0,
                title=form.cleaned_data["title"], public_description=form.cleaned_data["public_description"],
                offered_quantity=form.cleaned_data["offered_quantity"],
                collection_info=form.cleaned_data["collection_info"],
            )
        except DomainError as exc:
            _apply_errors(form, exc)
            return domain_error_response(request, exc, "catalogue/listing_form.html", ctx)
        messages.success(request, _("Listing updated."))
        return redirect("catalogue:listing_detail", pk=listing.pk)
    return render(request, "catalogue/listing_form.html", ctx)


@require_POST
@active_role_required
def listing_action(request, pk, action):
    form = ListingActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("The form was incomplete. Reload and try again."))
        return redirect("catalogue:listing_detail", pk=pk)
    try:
        CatalogueService.transition(actor_from(request), pk, action, expected_version=form.cleaned_data["version"],
                                    reason=form.cleaned_data["reason"])
    except DomainError as exc:
        if exc.status_code in (403, 404):
            return domain_error_response(request, exc)
        details = exc.field_errors.get("__all__", []) + [m for k, v in exc.field_errors.items()
                                                          if k != "__all__" for m in v]
        messages.error(request, " ".join([exc.message] + details))
        return redirect("catalogue:listing_detail", pk=pk)
    labels = {"submit": _("Submitted for release review."), "publish": _("Published to the exchange."),
              "pause": _("Paused. No new reservations can start."), "resume": _("Resumed."),
              "withdraw": _("Withdrawn."), "close": _("Closed.")}
    messages.success(request, labels.get(action, _("Updated.")))
    return redirect("catalogue:listing_detail", pk=pk)


def _apply_errors(form, exc: DomainError) -> None:
    for field, errs in exc.field_errors.items():
        for err in errs:
            form.add_error(field if field in form.fields else None, err)
    if not exc.field_errors:
        form.add_error(None, exc.message)


# ---------------------------------------------------------------------------
# Release review queue - TEST ADAPTER ONLY. Removed when Sinan's
# ApprovalService (workflow module) is configured.
# ---------------------------------------------------------------------------
def _fixture_port():
    port = get_adapter("RELEASE_APPROVALS")
    return port if getattr(port, "is_test_adapter", False) else None


@active_role_required
def release_queue(request):
    port = _fixture_port()
    if port is None:
        return render(request, "core/error.html", {"status": 404}, status=404)
    rows = list(port.pending_for(request.user))
    return render(request, "catalogue/release_queue.html", {"rows": rows, "form": ReleaseDecisionForm()})


@require_POST
@active_role_required
def release_decide(request, pk):
    port = _fixture_port()
    if port is None:
        return render(request, "core/error.html", {"status": 404}, status=404)
    listing = get_object_or_404(Listing.objects.select_related("asset"), pk=pk)
    form = ReleaseDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Choose a decision."))
        return redirect("catalogue:release_queue")
    try:
        port.decide(listing=listing, decider=request.user, status=form.cleaned_data["decision"],
                    reason=form.cleaned_data["reason"])
    except DomainError as exc:
        messages.error(request, exc.message)
        return redirect("catalogue:release_queue")
    CatalogueService.sync_release_outcome(listing)
    messages.success(request, _("Decision recorded."))
    return redirect("catalogue:release_queue")
