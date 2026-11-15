"""IdentityAdapter implementations (FR-01, NFR-08, IF-04).

``OIDCIdentityAdapter`` is the planned KU SSO connector: authorisation code
with PKCE, state and nonce; the ID token is validated for issuer, audience,
signature and expiry against the published identity metadata. KU performs
the Microsoft Authenticator step. No university password, Authenticator
code or token is stored by UNIVENTORY - only the verified stable subject.

``DevIdentityAdapter`` is a clearly labelled test adapter for local
development. It is refused unless DEBUG is on and UNIVENTORY_DEV_LOGIN is
set; its sign-ins carry issuer ``dev-test`` and are never presented as KU
SSO.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache

SESSION_KEY = "univentory_oidc_flow"


class IdentityError(Exception):
    """Sign-in failed or was cancelled. ``reason`` is safe to show."""

    def __init__(self, reason: str, *, cancelled: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.cancelled = cancelled


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    email: str = ""
    display_name: str = ""


class OIDCIdentityAdapter:
    label = "Khalifa University sign-in"
    is_test_adapter = False

    def __init__(self, config: dict | None = None, http=None):
        self.config = config or settings.UNIVENTORY_OIDC
        self.http = http or requests

    @property
    def configured(self) -> bool:
        return all(self.config.get(k) for k in ("ISSUER", "CLIENT_ID", "REDIRECT_URI"))

    # -- discovery ---------------------------------------------------------
    def metadata(self) -> dict:
        key = f"oidc-metadata:{self.config['ISSUER']}"
        data = cache.get(key)
        if data is None:
            url = self.config["ISSUER"].rstrip("/") + "/.well-known/openid-configuration"
            response = self.http.get(url, timeout=self.config.get("TIMEOUT_SECONDS", 10))
            response.raise_for_status()
            data = response.json()
            if data.get("issuer") != self.config["ISSUER"]:
                raise IdentityError("Identity metadata issuer does not match configuration.")
            cache.set(key, data, 3600)
        return data

    # -- step 1: redirect to KU -------------------------------------------
    def begin(self, request, next_url: str = "") -> str:
        if not self.configured:
            raise IdentityError("University sign-in is not configured on this server.")
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        request.session[SESSION_KEY] = {"state": state, "nonce": nonce, "verifier": verifier, "next": next_url}
        params = {
            "response_type": "code",
            "client_id": self.config["CLIENT_ID"],
            "redirect_uri": self.config["REDIRECT_URI"],
            "scope": self.config.get("SCOPES", "openid profile email"),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return self.metadata()["authorization_endpoint"] + "?" + urlencode(params)

    # -- step 2: callback ---------------------------------------------------
    def complete(self, request) -> tuple[VerifiedIdentity, str]:
        flow = request.session.pop(SESSION_KEY, None)
        error = request.GET.get("error")
        if error:
            cancelled = error in {"access_denied", "login_required", "consent_required", "interaction_required"}
            raise IdentityError(
                "Sign-in was cancelled." if cancelled else "University sign-in did not complete.",
                cancelled=cancelled,
            )
        if not flow:
            raise IdentityError("The sign-in session expired. Please start again.")
        if not secrets.compare_digest(request.GET.get("state", ""), flow["state"]):
            raise IdentityError("The sign-in response could not be verified.")
        code = request.GET.get("code")
        if not code:
            raise IdentityError("The sign-in response was incomplete.")

        meta = self.metadata()
        token_response = self.http.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config["REDIRECT_URI"],
                "client_id": self.config["CLIENT_ID"],
                "client_secret": self.config.get("CLIENT_SECRET", ""),
                "code_verifier": flow["verifier"],
            },
            timeout=self.config.get("TIMEOUT_SECONDS", 10),
        )
        if token_response.status_code != 200:
            raise IdentityError("University sign-in did not complete.")
        id_token = token_response.json().get("id_token")
        if not id_token:
            raise IdentityError("University sign-in did not return an identity.")
        claims = self.validate_id_token(id_token, nonce=flow["nonce"], metadata=meta)
        identity = VerifiedIdentity(
            issuer=claims["iss"],
            subject=str(claims["sub"]),
            email=claims.get("email") or claims.get("preferred_username") or claims.get("upn", ""),
            display_name=claims.get("name", ""),
        )
        return identity, flow.get("next", "")

    def validate_id_token(self, id_token: str, *, nonce: str, metadata: dict) -> dict:
        import jwt

        try:
            signing_key = jwt.PyJWKClient(metadata["jwks_uri"]).get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "PS256"],
                audience=self.config["CLIENT_ID"],
                issuer=self.config["ISSUER"],
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
                leeway=60,
            )
        except jwt.PyJWTError as exc:
            raise IdentityError("The identity token could not be verified.") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise IdentityError("The identity token could not be verified.")
        return claims

    def end_session_url(self) -> str:
        if not self.configured:
            return ""
        try:
            endpoint = self.metadata().get("end_session_endpoint", "")
        except Exception:  # identity provider unavailable; local logout still applies
            return ""
        if not endpoint:
            return ""
        params = {"client_id": self.config["CLIENT_ID"]}
        if self.config.get("END_SESSION_REDIRECT"):
            params["post_logout_redirect_uri"] = self.config["END_SESSION_REDIRECT"]
        return endpoint + "?" + urlencode(params)


class DevIdentityAdapter:
    """Test adapter. Not KU SSO. Only available in DEBUG with the flag on."""

    label = "Development sign-in (test adapter - not KU SSO)"
    issuer = "dev-test"
    is_test_adapter = True

    @staticmethod
    def enabled() -> bool:
        return bool(settings.DEBUG and settings.UNIVENTORY_DEV_LOGIN)

    def identity_for(self, user) -> VerifiedIdentity:
        if not self.enabled():
            raise IdentityError("Development sign-in is disabled.")
        if user.identity_issuer != self.issuer:
            raise IdentityError("Only development accounts can use development sign-in.")
        return VerifiedIdentity(
            issuer=self.issuer, subject=user.identity_subject, email=user.email, display_name=user.display_name
        )
