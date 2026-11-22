"""Attach the server-derived actor context to every request."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.contrib.auth import logout
from django.shortcuts import redirect

from identity.adapters import DevIdentityAdapter
from identity.models import AppUser
from identity.policy import AccessPolicy


class ActorContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Multi-tab demo support: allow tab-scoped persona via ?as_user= in dev mode
        if DevIdentityAdapter.enabled():
            as_param = request.GET.get("as_user") or request.POST.get("as_user") or request.headers.get("X-As-User")
            if as_param:
                target_user = None
                as_str = str(as_param).strip()
                if as_str.isdigit():
                    target_user = AppUser.objects.filter(pk=int(as_str), is_active=True).first()
                if not target_user:
                    target_user = AppUser.objects.filter(username=as_str, is_active=True).first()
                if target_user:
                    request.user = target_user
                    request._cached_user = target_user
                    request.as_user_id = str(target_user.pk)

        user = getattr(request, "user", None)
        request.actor_grants = ()
        request.actor_role_codes = set()
        if user is not None and user.is_authenticated:
            if not user.is_active:
                # Disabled application access ends the session immediately.
                logout(request)
                return redirect("identity:login")
            AccessPolicy.refresh(user)
            request.actor_grants = AccessPolicy.grants(user)
            request.actor_role_codes = {g.role for g in request.actor_grants}

        response = self.get_response(request)

        # Propagate as_user on internal redirects so tabs never lose their persona
        as_id = getattr(request, "as_user_id", None)
        if as_id and response.status_code in {301, 302, 303, 307, 308}:
            location = response.get("Location", "")
            if location and (not location.startswith(("http://", "https://", "//")) or location.startswith(("http://127.0.0.1", "http://localhost"))):
                parsed = urlparse(location)
                query = dict(parse_qsl(parsed.query))
                if "as_user" not in query:
                    query["as_user"] = as_id
                    new_query = urlencode(query)
                    new_location = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                    response["Location"] = new_location

        return response
