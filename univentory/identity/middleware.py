"""Attach the server-derived actor context to every request."""
from django.contrib.auth import logout
from django.shortcuts import redirect

from identity.policy import AccessPolicy


class ActorContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
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
        return self.get_response(request)
