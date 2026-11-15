"""Thin-view helpers shared by every module (owner: Jesher).

Views parse input, identify the actor, call a service and render. These
helpers keep access gates and error outcomes identical across modules.
"""
from __future__ import annotations

import uuid
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render

from core.contracts import ActorContext, DomainError
from identity.policy import AccessPolicy


def new_operation_key() -> str:
    return uuid.uuid4().hex


def actor_from(request) -> ActorContext:
    """Build the actor context. The operation key comes from the form so a
    repeated submission of the same rendered form is recognised (IF-08)."""
    key = (request.POST.get("operation_key") or "").strip()[:64]
    return ActorContext(user=request.user, operation_key=key)


def active_role_required(view):
    """Signed in AND holding at least one active grant (FR-02).

    An authenticated account without a role receives no protected records.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not AccessPolicy.has_any_role(request.user):
            return render(request, "core/no_access.html", status=403)
        return view(request, *args, **kwargs)

    return wrapper


def policy_required(check):
    """Gate a view on an AccessPolicy predicate taking only the user."""

    def decorator(view):
        @wraps(view)
        @active_role_required
        def wrapper(request, *args, **kwargs):
            if not check(request.user):
                return permission_denied_response(request)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def permission_denied_response(request, message: str = ""):
    return render(request, "core/error.html", {"status": 403, "message": message}, status=403)


def domain_error_response(request, exc: DomainError, template: str | None = None, context: dict | None = None):
    """Render a service error with its documented status code.

    Validation errors re-render the originating form (values preserved);
    other outcomes use the shared error page with the permitted next action.
    """
    if template and exc.status_code in (400, 409, 422):
        ctx = dict(context or {})
        ctx.setdefault("domain_error", exc)
        return render(request, template, ctx, status=exc.status_code)
    return render(
        request,
        "core/error.html",
        {"status": exc.status_code, "message": exc.message, "next_action": exc.next_action},
        status=exc.status_code,
    )
