"""Authentication backend that accepts only a verified identity object."""
from django.contrib.auth.backends import BaseBackend

from identity.models import AppUser


class UniversityIdentityBackend(BaseBackend):
    """Maps a ``VerifiedIdentity`` to a local account.

    There is no username/password path. An account is provisioned on first
    verified sign-in with no roles; it receives no protected records until a
    system administrator grants a role (FR-02).
    """

    def authenticate(self, request, verified_identity=None, **kwargs):
        if verified_identity is None:
            return None
        user, _ = AppUser.objects.get_or_provision(
            issuer=verified_identity.issuer,
            subject=verified_identity.subject,
            email=verified_identity.email,
            display_name=verified_identity.display_name,
        )
        return user if user.is_active else None

    def get_user(self, user_id):
        try:
            user = AppUser.objects.get(pk=user_id)
        except AppUser.DoesNotExist:
            return None
        return user if user.is_active else None
