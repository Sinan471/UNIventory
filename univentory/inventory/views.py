"""Inventory views: My Assets, editor, detail/history, quantities, evidence."""
from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from catalogue.models import Listing, ListingState
from catalogue.services import CatalogueService
from core.contracts import DomainError, NotPermitted
from core.web import active_role_required, actor_from, domain_error_response, new_operation_key
from identity.models import Category
from identity.policy import AccessPolicy
from inventory.forms import (
    AdjustForm,
    AssetForm,
    AttachmentForm,
    MyAssetsFilterForm,
    SplitForm,
    UseStateForm,
    WithdrawForm,
)
from inventory.models import AssetPortion, Attachment, Lifecycle, TrackingType
from inventory.services import AssetInput, AssetQueryService, AttachmentService, InventoryService


def _apply_errors(form, exc: DomainError) -> None:
    for field, errs in exc.field_errors.items():
        for err in errs:
            if field.startswith("spec_") and field not in form.fields:
                category_id = form.data.get("category")
                candidate = f"spec_{category_id}_{field[5:]}"
                field = candidate if candidate in form.fields else None
            form.add_error(field if field in form.fields else None, err)
    if not exc.field_errors:
        form.add_error(None, exc.message)


@active_role_required
def my_assets(request):
    form = MyAssetsFilterForm(request.GET or None)
    qs = AssetQueryService.records_for(request.user)
    if form.is_valid():
        if q := form.cleaned_data["q"]:
            qs = qs.filter(Q(title__icontains=q) | Q(asset_code__icontains=q) | Q(description__icontains=q))
        if state := form.cleaned_data["lifecycle"]:
            qs = qs.filter(portions__lifecycle_state=state, portions__is_active_leaf=True).distinct()
    page = Paginator(qs.order_by("-updated_at"), 25).get_page(request.GET.get("page"))
    rows = []
    for asset in page.object_list:
        summary = AssetQueryService.quantity_summary(asset)
        listing = asset.listings.filter(state__in=ListingState.open_states()).first()
        states = sorted(set(asset.portions.filter(is_active_leaf=True, quantity__gt=0)
                            .values_list("lifecycle_state", flat=True)))
        rows.append({"asset": asset, "summary": summary, "listing": listing,
                     "states": [Lifecycle(s) for s in states]})
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "inventory/my_assets.html", {
        "form": form, "page": page, "rows": rows, "querystring": query.urlencode(),
        "can_register": bool(AccessPolicy.registrable_departments(request.user)),
    })


def _asset_input(form, user) -> AssetInput:
    cd = form.cleaned_data
    return AssetInput(
        title=cd["title"], description=cd["description"], category=cd["category"], department=cd["department"],
        location=cd["location"], tracking_type=cd["tracking_type"], quantity=cd["quantity"], unit=cd["unit"],
        condition=cd["condition"], subcategory=cd["subcategory"], tags=form.tag_list(), material=cd["material"],
        weight_kg=cd["weight_kg"], legal_owner=cd["legal_owner"], acquisition_date=cd["acquisition_date"],
        acquisition_date_unknown=cd["acquisition_date_unknown"], estimated_value_aed=cd["estimated_value_aed"],
        estimated_value_unknown=cd["estimated_value_unknown"], ownership_restriction=cd["ownership_restriction"],
        restriction_notes=cd["restriction_notes"], release_rights_confirmed=cd["release_rights_confirmed"],
        is_hazardous=cd["is_hazardous"], is_data_bearing=cd["is_data_bearing"], is_regulated=cd["is_regulated"],
        handling_notes=cd["handling_notes"], specifications=form.specs_for(cd["category"]),
        provenance=cd["provenance"], custodian=user,
    )


def _editor_context(form, asset=None):
    return {
        "form": form,
        "asset": asset,
        "categories": Category.objects.active(),
        "subcategories": {c.pk: c.subcategories for c in Category.objects.active()},
    }


@active_role_required
def asset_new(request):
    departments = AccessPolicy.registrable_departments(request.user)
    if not departments:
        return domain_error_response(request, NotPermitted(_("You need the Asset Custodian role to register assets.")))
    initial = {"operation_key": new_operation_key()}
    if len(departments) == 1:
        initial["department"] = departments[0]
    form = AssetForm(request.POST or None, departments=departments, initial=initial)
    if request.method == "POST":
        if not form.is_valid():
            return render(request, "inventory/asset_form.html", _editor_context(form), status=422)
        try:
            asset = InventoryService.register(actor_from(request), _asset_input(form, request.user),
                                              activate_as=form.cleaned_data.get("activate_as") or None)
        except DomainError as exc:
            _apply_errors(form, exc)
            return domain_error_response(request, exc, "inventory/asset_form.html", _editor_context(form))
        messages.success(request, _("Asset %(code)s registered.") % {"code": asset.asset_code})
        return redirect("inventory:asset_detail", pk=asset.pk)
    return render(request, "inventory/asset_form.html", _editor_context(form))


@active_role_required
def asset_edit(request, pk):
    try:
        asset = AssetQueryService.get_record(request.user, pk)
    except DomainError as exc:
        return domain_error_response(request, exc)
    if not AccessPolicy.can_edit_asset(request.user, asset):
        return domain_error_response(request, NotPermitted(_("Only the assigned custodian can edit this record.")))
    form = AssetForm(request.POST or None, editing=True, initial=AssetForm.initial_from(asset))
    ctx = _editor_context(form, asset)
    if request.method == "POST":
        if not form.is_valid():
            return render(request, "inventory/asset_form.html", ctx, status=422)
        cd = form.cleaned_data
        changes = {
            "title": cd["title"], "description": cd["description"], "category": cd["category"],
            "subcategory": cd["subcategory"], "tags": form.tag_list(), "material": cd["material"],
            "weight_kg": cd["weight_kg"], "legal_owner": cd["legal_owner"], "location": cd["location"],
            "acquisition_date": cd["acquisition_date"], "acquisition_date_unknown": cd["acquisition_date_unknown"],
            "estimated_value_aed": cd["estimated_value_aed"], "estimated_value_unknown": cd["estimated_value_unknown"],
            "ownership_restriction": cd["ownership_restriction"], "restriction_notes": cd["restriction_notes"],
            "release_rights_confirmed": cd["release_rights_confirmed"], "is_hazardous": cd["is_hazardous"],
            "is_data_bearing": cd["is_data_bearing"], "is_regulated": cd["is_regulated"],
            "handling_notes": cd["handling_notes"], "specifications": form.specs_for(cd["category"]),
            "provenance": cd["provenance"],
        }
        try:
            InventoryService.update(actor_from(request), asset.pk, changes, expected_version=cd["version"] or 0)
        except DomainError as exc:
            _apply_errors(form, exc)
            if exc.status_code == 409:
                ctx["stale"] = True
            return domain_error_response(request, exc, "inventory/asset_form.html", ctx)
        messages.success(request, _("Changes saved."))
        return redirect("inventory:asset_detail", pk=asset.pk)
    return render(request, "inventory/asset_form.html", ctx)


@active_role_required
def asset_detail(request, pk):
    try:
        asset = AssetQueryService.get_record(request.user, pk)
    except DomainError as exc:
        return domain_error_response(request, exc)
    can_edit = AccessPolicy.can_edit_asset(request.user, asset)
    portions = list(AssetQueryService.current_portions(asset))
    listings = list(asset.listings.select_related("department").order_by("-created_at"))
    for listing in listings:
        listing.free_now = CatalogueService.free_quantity(listing)
    open_listing = next((l for l in listings if l.state in ListingState.open_states()), None)
    return render(request, "inventory/asset_detail.html", {
        "asset": asset,
        "can_edit": can_edit,
        "summary": AssetQueryService.quantity_summary(asset),
        "portions": portions,
        "events": AssetQueryService.history(request.user, asset)[:100],
        "attachments": asset.attachments.select_related("uploaded_by").all(),
        "listings": listings,
        "open_listing": open_listing,
        "spec_rows": [
            (f.get("label", f["key"]), asset.specifications.get(f["key"]), f.get("unit", ""))
            for f in asset.category.spec_schema if asset.specifications.get(f["key"]) not in (None, "")
        ],
        "is_batch": asset.tracking_type == TrackingType.BATCH,
        "is_draft": asset.record_status == "DRAFT",
        "upload_form": AttachmentForm(initial={"operation_key": new_operation_key()}),
        "op_key": new_operation_key(),
        "lifecycle": Lifecycle,
    })


def _portion_for(request, portion_id):
    portion = AssetPortion.objects.select_related("asset").filter(pk=portion_id).first()
    if portion is None or not AccessPolicy.can_view_asset_record(request.user, portion.asset):
        return None
    return portion


def _portion_command(request, portion_id, form_class, run, success):
    portion = _portion_for(request, portion_id)
    if portion is None:
        return render(request, "core/error.html", {"status": 404}, status=404)
    form = form_class(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect("inventory:asset_detail", pk=portion.asset_id)
    try:
        run(actor_from(request), portion, form.cleaned_data)
    except DomainError as exc:
        if exc.status_code in (403, 404):
            return domain_error_response(request, exc)
        detail = " ".join(m for errs in exc.field_errors.values() for m in errs)
        messages.error(request, f"{exc.message} {detail}".strip())
        return redirect("inventory:asset_detail", pk=portion.asset_id)
    messages.success(request, success)
    return redirect("inventory:asset_detail", pk=portion.asset_id)


@require_POST
@active_role_required
def portion_split(request, pk):
    return _portion_command(
        request, pk, SplitForm,
        lambda actor, portion, cd: InventoryService.split_batch(
            actor, portion.pk, cd["quantity"], expected_version=cd["version"], reason=cd["reason"]),
        _("Batch split. Quantities remain conserved."),
    )


@require_POST
@active_role_required
def portion_adjust(request, pk):
    return _portion_command(
        request, pk, AdjustForm,
        lambda actor, portion, cd: InventoryService.adjust_quantity(
            actor, portion.pk, cd["quantity"], reason=cd["reason"], expected_version=cd["version"]),
        _("Quantity corrected and recorded in the ledger."),
    )


@require_POST
@active_role_required
def portion_state(request, pk):
    return _portion_command(
        request, pk, UseStateForm,
        lambda actor, portion, cd: InventoryService.set_use_state(
            actor, portion.pk, cd["to_state"], expected_version=cd["version"], quantity=cd["quantity"]),
        _("Life-cycle state updated."),
    )


@require_POST
@active_role_required
def asset_activate(request, pk):
    try:
        asset = AssetQueryService.get_record(request.user, pk)
        InventoryService.activate(actor_from(request), asset, request.POST.get("to_state", ""))
    except DomainError as exc:
        if exc.status_code in (403, 404):
            return domain_error_response(request, exc)
        detail = " ".join(m for errs in exc.field_errors.values() for m in errs)
        messages.error(request, f"{exc.message} {detail}".strip())
        return redirect("inventory:asset_detail", pk=pk)
    messages.success(request, _("Record activated."))
    return redirect("inventory:asset_detail", pk=pk)


@require_POST
@active_role_required
def attachment_upload(request, pk):
    try:
        asset = AssetQueryService.get_record(request.user, pk)
    except DomainError as exc:
        return domain_error_response(request, exc)
    form = AttachmentForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect(f"{asset_detail_url(asset)}#evidence")
    try:
        attachment = AttachmentService.store(
            actor_from(request), asset, form.cleaned_data["file"], access_class=form.cleaned_data["access_class"],
            description=form.cleaned_data["description"],
        )
    except DomainError as exc:
        if exc.status_code in (403, 404):
            return domain_error_response(request, exc)
        detail = " ".join(m for errs in exc.field_errors.values() for m in errs)
        messages.error(request, f"{exc.message} {detail}".strip())
        return redirect(f"{asset_detail_url(asset)}#evidence")
    if attachment.status == "QUARANTINED":
        messages.warning(request, _("The file was quarantined and cannot be opened: %(r)s") % {
            "r": attachment.status_reason})
    else:
        messages.success(request, _("Evidence added."))
    return redirect(f"{asset_detail_url(asset)}#evidence")


def asset_detail_url(asset) -> str:
    from django.urls import reverse

    return reverse("inventory:asset_detail", args=[asset.pk])


@active_role_required
def attachment_download(request, pk):
    try:
        attachment, path = AttachmentService.open_for(request.user, pk)
    except DomainError as exc:
        return domain_error_response(request, exc)
    response = FileResponse(open(path, "rb"), content_type=attachment.content_type,
                            as_attachment=not attachment.is_image, filename=attachment.original_name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
@active_role_required
def attachment_withdraw(request, pk):
    attachment = Attachment.objects.select_related("asset").filter(pk=pk).first()
    if attachment is None or not AccessPolicy.can_view_asset_record(request.user, attachment.asset):
        return render(request, "core/error.html", {"status": 404}, status=404)
    form = WithdrawForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("A reason is required."))
    else:
        try:
            AttachmentService.withdraw(actor_from(request), attachment, form.cleaned_data["reason"])
            messages.success(request, _("Evidence withdrawn. It remains in the record history."))
        except DomainError as exc:
            if exc.status_code in (403, 404):
                return domain_error_response(request, exc)
            messages.error(request, exc.message)
    return redirect(f"{asset_detail_url(attachment.asset)}#evidence")
