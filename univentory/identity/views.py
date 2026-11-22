"""Sign-in, sign-out and administration views. Thin by design."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from core.contracts import DomainError
from core.web import actor_from, domain_error_response, new_operation_key, policy_required
from identity.adapters import DevIdentityAdapter, IdentityError, OIDCIdentityAdapter
from identity.forms import (
    AccountStatusForm,
    CategoryForm,
    DepartmentForm,
    GrantRoleForm,
    LocationForm,
    PersonSearchForm,
    RevokeForm,
    dev_personas,
    dev_users,
)
from identity.models import AppUser, Category, Department, Location, UserRole
from identity.policy import AccessPolicy
from identity.services import ReferenceDataService, RoleGrantService


def _safe_next(request, candidate: str) -> str:
    if candidate and url_has_allowed_host_and_scheme(candidate, {request.get_host()}, request.is_secure()):
        return candidate
    return "/"


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------
@require_GET
def login_page(request):
    if request.user.is_authenticated and not DevIdentityAdapter.enabled():
        return redirect("core:home")
    oidc = OIDCIdentityAdapter()
    return render(
        request,
        "identity/login.html",
        {
            "next": request.GET.get("next", ""),
            "sso_configured": oidc.configured,
            "dev_enabled": DevIdentityAdapter.enabled(),
            "dev_users": dev_users() if DevIdentityAdapter.enabled() else [],
            "dev_personas": dev_personas() if DevIdentityAdapter.enabled() else [],
            "failure": request.GET.get("failure", ""),
        },
    )


@require_POST
def sso_start(request):
    try:
        url = OIDCIdentityAdapter().begin(request, next_url=request.POST.get("next", ""))
    except IdentityError as exc:
        return render(request, "identity/login_failed.html", {"reason": exc.reason}, status=503)
    except Exception:
        return render(
            request,
            "identity/login_failed.html",
            {"reason": _("The university identity service is unavailable. Try again shortly.")},
            status=503,
        )
    return redirect(url)


@require_GET
def sso_callback(request):
    try:
        identity, next_url = OIDCIdentityAdapter().complete(request)
    except IdentityError as exc:
        return render(
            request,
            "identity/login_failed.html",
            {"reason": exc.reason, "cancelled": exc.cancelled},
            status=401,
        )
    user = authenticate(request, verified_identity=identity)
    if user is None:
        return render(
            request,
            "identity/login_failed.html",
            {"reason": _("Your UNIventory access is disabled. Contact the system administrator.")},
            status=403,
        )
    login(request, user)
    return redirect(_safe_next(request, next_url))


@require_POST
def dev_login(request):
    adapter = DevIdentityAdapter()
    if not adapter.enabled():
        raise Http404()
    user_id = request.POST.get("user_id", "")
    if not user_id.isdigit():
        raise Http404()
    user = get_object_or_404(AppUser, pk=int(user_id), identity_issuer=adapter.issuer)
    try:
        identity = adapter.identity_for(user)
    except IdentityError as exc:
        return render(request, "identity/login_failed.html", {"reason": exc.reason}, status=401)
    authed = authenticate(request, verified_identity=identity)
    if authed is None:
        return render(request, "identity/login_failed.html", {"reason": _("This account is disabled.")}, status=403)
    login(request, authed)
    target_next = _safe_next(request, request.POST.get("next", ""))
    sep = "&" if "?" in target_next else "?"
    return redirect(f"{target_next}{sep}as_user={user.pk}")


@require_POST
def logout_view(request):
    end_session = ""
    if request.user.is_authenticated and request.user.identity_issuer != DevIdentityAdapter.issuer:
        end_session = OIDCIdentityAdapter().end_session_url()
    logout(request)  # flushes the session server-side (FR-01)
    if end_session:
        return redirect(end_session)
    return redirect("identity:signed_out")


def signed_out(request):
    return render(request, "identity/signed_out.html")


# ---------------------------------------------------------------------------
# Administration: reference data (FR-04)
# ---------------------------------------------------------------------------
REFERENCE_KINDS = {
    "departments": (Department, DepartmentForm, _("Departments")),
    "locations": (Location, LocationForm, _("Locations")),
    "categories": (Category, CategoryForm, _("Categories")),
}


def _kind_or_404(kind):
    if kind not in REFERENCE_KINDS:
        raise Http404()
    return REFERENCE_KINDS[kind]


@policy_required(AccessPolicy.can_manage_reference_data)
def admin_home(request):
    return redirect("identity:reference_list", kind="departments")


@policy_required(AccessPolicy.can_manage_reference_data)
def reference_list(request, kind):
    model, _form, title = _kind_or_404(kind)
    show = request.GET.get("show", "active")
    qs = model.objects.all() if show == "all" else model.objects.active()
    return render(
        request,
        "identity/reference_list.html",
        {"kind": kind, "title": title, "rows": qs.order_by("name"), "show": show, "kinds": REFERENCE_KINDS},
    )


@policy_required(AccessPolicy.can_manage_reference_data)
def reference_edit(request, kind, pk=None):
    model, form_class, title = _kind_or_404(kind)
    instance = get_object_or_404(model, pk=pk) if pk else None
    form = form_class(request.POST or None, instance=instance, initial={"operation_key": new_operation_key()})
    ctx = {"kind": kind, "title": title, "form": form, "instance": instance, "kinds": REFERENCE_KINDS}
    if request.method == "POST":
        if not form.is_valid():
            return render(request, "identity/reference_form.html", ctx, status=422)
        try:
            ReferenceDataService.save(actor_from(request), form.save(commit=False))
        except DomainError as exc:
            for field, errs in exc.field_errors.items():
                for err in errs:
                    form.add_error(field if field in form.fields else None, err)
            return domain_error_response(request, exc, "identity/reference_form.html", ctx)
        messages.success(request, _("Saved."))
        return redirect("identity:reference_list", kind=kind)
    return render(request, "identity/reference_form.html", ctx)


@require_POST
@policy_required(AccessPolicy.can_manage_reference_data)
def reference_toggle(request, kind, pk):
    model, _form, _title = _kind_or_404(kind)
    instance = get_object_or_404(model, pk=pk)
    ReferenceDataService.set_active(actor_from(request), instance, request.POST.get("active") == "1",
                                    request.POST.get("reason", ""))
    messages.success(request, _("Updated."))
    return redirect("identity:reference_list", kind=kind)


# ---------------------------------------------------------------------------
# Administration: people and role grants (FR-03)
# ---------------------------------------------------------------------------
@policy_required(AccessPolicy.can_manage_roles)
def people(request):
    form = PersonSearchForm(request.GET or None)
    rows = form.filter(AppUser.objects.all()).prefetch_related("role_grants__role", "role_grants__department")
    return render(request, "identity/people.html", {"form": form, "rows": rows[:200], "kinds": REFERENCE_KINDS})


@policy_required(AccessPolicy.can_manage_roles)
def person_detail(request, pk):
    person = get_object_or_404(AppUser, pk=pk)
    grant_form = GrantRoleForm(request.POST or None)
    if request.method == "POST":
        if grant_form.is_valid():
            try:
                RoleGrantService.grant(
                    actor_from(request),
                    user=person,
                    role=grant_form.cleaned_data["role"],
                    department=grant_form.cleaned_data["department"],
                    reason=grant_form.cleaned_data["reason"],
                    effective_to=grant_form.cleaned_data["effective_to"],
                )
                messages.success(request, _("Role granted."))
                return redirect("identity:person_detail", pk=pk)
            except DomainError as exc:
                for field, errs in exc.field_errors.items():
                    for err in errs:
                        grant_form.add_error(field if field in grant_form.fields else None, err)
                if not exc.field_errors:
                    grant_form.add_error(None, exc.message)
    grants = UserRole.objects.filter(user=person).select_related("role", "department", "granted_by", "revoked_by")
    return render(
        request,
        "identity/person_detail.html",
        {
            "person": person,
            "grants": grants,
            "grant_form": grant_form,
            "revoke_form": RevokeForm(),
            "status_form": AccountStatusForm(),
            "kinds": REFERENCE_KINDS,
        },
        status=422 if request.method == "POST" else 200,
    )


@require_POST
@policy_required(AccessPolicy.can_manage_roles)
def revoke_grant(request, pk):
    grant = get_object_or_404(UserRole, pk=pk)
    form = RevokeForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("A reason is required to revoke a role."))
        return redirect("identity:person_detail", pk=grant.user_id)
    try:
        RoleGrantService.revoke(actor_from(request), grant, form.cleaned_data["reason"])
        messages.success(request, _("Role revoked. It applies to the person's next action."))
    except DomainError as exc:
        messages.error(request, exc.message)
    return redirect("identity:person_detail", pk=grant.user_id)


@require_POST
@policy_required(AccessPolicy.can_manage_roles)
def account_status(request, pk):
    person = get_object_or_404(AppUser, pk=pk)
    form = AccountStatusForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("A reason is required."))
        return redirect("identity:person_detail", pk=pk)
    try:
        RoleGrantService.set_account_active(actor_from(request), person, form.cleaned_data["active"],
                                            form.cleaned_data["reason"])
        messages.success(request, _("Account updated."))
    except DomainError as exc:
        messages.error(request, exc.message)
    return redirect("identity:person_detail", pk=pk)
