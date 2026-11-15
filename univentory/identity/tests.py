"""Access, identity and reference-data tests (FR-01..FR-04, NFR-08, NFR-09, NFR-14)."""
from unittest import mock

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.contracts import NotPermitted, ValidationFailed
from core.testing import World, actor, register
from identity.adapters import SESSION_KEY, IdentityError, OIDCIdentityAdapter
from identity.models import Location, Role, UserRole
from identity.policy import AccessPolicy
from identity.services import ReferenceDataService, RoleGrantService


def sign_in(client: Client, user) -> None:
    """Test helper: establishes a session without any password."""
    client.force_login(user, backend="identity.backends.UniversityIdentityBackend")


class AccessPolicyTests(TestCase):
    def setUp(self):
        self.w = World()

    def test_account_without_role_receives_no_protected_records(self):
        client = Client()
        sign_in(client, self.w.norole)
        for url in ["/exchange/", "/inventory/", "/design/"]:
            response = client.get(url)
            self.assertEqual(response.status_code, 403, url)
            self.assertContains(response, "no UNIventory role", status_code=403)

    def test_unauthenticated_requests_redirect_to_sign_in(self):
        response = Client().get("/inventory/")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("identity:login"), response["Location"])

    def test_revocation_applies_to_next_request_in_same_session(self):
        client = Client()
        sign_in(client, self.w.custodian)
        self.assertEqual(client.get("/inventory/new/").status_code, 200)
        grant = UserRole.objects.get(user=self.w.custodian)
        RoleGrantService.revoke(actor(self.w.admin), grant, "Moved to another team")
        self.assertEqual(client.get("/inventory/new/").status_code, 403)

    def test_disabled_account_session_ends(self):
        client = Client()
        sign_in(client, self.w.custodian)
        RoleGrantService.set_account_active(actor(self.w.admin), self.w.custodian, False, "Left KU")
        response = client.get("/inventory/")
        self.assertEqual(response.status_code, 302)

    def test_cross_department_record_is_not_disclosed(self):
        asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        client = Client()
        sign_in(client, self.w.other_custodian)
        for url in [f"/inventory/{asset.pk}/", f"/inventory/{asset.pk}/edit/", f"/exchange/assets/{asset.pk}/list/"]:
            self.assertEqual(client.get(url).status_code, 404, url)
        missing = client.get("/inventory/999999/")
        self.assertEqual(missing.status_code, 404)

    def test_department_rep_reads_but_cannot_edit(self):
        asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        self.assertTrue(AccessPolicy.can_view_asset_record(self.w.rep, asset))
        self.assertFalse(AccessPolicy.can_edit_asset(self.w.rep, asset))
        self.assertFalse(AccessPolicy.can_edit_asset(self.w.custodian2, asset))  # not the assigned custodian

    def test_sysadmin_has_no_business_authority(self):
        self.assertFalse(AccessPolicy.can_register_asset(self.w.admin))
        self.assertFalse(AccessPolicy.has_role(self.w.admin, Role.DEPT_REP))

    def test_session_inactivity_limit_is_thirty_minutes(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 1800)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)


class SignInTests(TestCase):
    def setUp(self):
        self.w = World()

    def test_logout_requires_post_and_ends_session(self):
        client = Client()
        sign_in(client, self.w.custodian)
        self.assertEqual(client.get(reverse("identity:logout")).status_code, 405)
        response = client.post(reverse("identity:logout"))
        self.assertRedirects(response, reverse("identity:signed_out"))
        self.assertEqual(client.get("/inventory/").status_code, 302)

    def test_dev_login_is_refused_outside_debug(self):
        response = Client().post(reverse("identity:dev_login"), {"user_id": self.w.custodian.pk})
        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=True, UNIVENTORY_DEV_LOGIN=True)
    def test_dev_login_only_for_dev_issuer_accounts(self):
        self.w.custodian.identity_issuer = "https://login.ku.ac.ae"
        self.w.custodian.save()
        response = Client().post(reverse("identity:dev_login"), {"user_id": self.w.custodian.pk})
        self.assertEqual(response.status_code, 404)

    def test_cancelled_sso_is_denied(self):
        client = Client()
        session = client.session
        session[SESSION_KEY] = {"state": "abc", "nonce": "n", "verifier": "v", "next": ""}
        session.save()
        response = client.get(reverse("identity:sso_callback"), {"error": "access_denied", "state": "abc"})
        self.assertEqual(response.status_code, 401)
        self.assertContains(response, "cancelled", status_code=401)
        self.assertEqual(client.get("/inventory/").status_code, 302)

    def test_state_mismatch_is_rejected(self):
        client = Client()
        session = client.session
        session[SESSION_KEY] = {"state": "expected", "nonce": "n", "verifier": "v", "next": ""}
        session.save()
        response = client.get(reverse("identity:sso_callback"), {"code": "x", "state": "forged"})
        self.assertEqual(response.status_code, 401)

    def test_begin_uses_pkce_state_and_nonce(self):
        adapter = OIDCIdentityAdapter(config={"ISSUER": "https://idp.example", "CLIENT_ID": "cid",
                                              "REDIRECT_URI": "https://app/cb", "SCOPES": "openid"})
        request = mock.Mock(session={})
        with mock.patch.object(adapter, "metadata", return_value={"authorization_endpoint": "https://idp.example/auth"}):
            url = adapter.begin(request)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=", url)
        self.assertIn("nonce=", url)
        flow = request.session[SESSION_KEY]
        self.assertNotIn(flow["verifier"], url)  # verifier never leaves the server

    def test_id_token_nonce_mismatch_rejected(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode({"iss": "https://idp.example", "aud": "cid", "sub": "123", "nonce": "other",
                            "exp": 9999999999, "iat": 1}, key, algorithm="RS256")
        adapter = OIDCIdentityAdapter(config={"ISSUER": "https://idp.example", "CLIENT_ID": "cid", "REDIRECT_URI": "x"})
        fake_key = mock.Mock(key=key.public_key())
        with mock.patch("jwt.PyJWKClient") as client_cls:
            client_cls.return_value.get_signing_key_from_jwt.return_value = fake_key
            with self.assertRaises(IdentityError):
                adapter.validate_id_token(token, nonce="expected", metadata={"jwks_uri": "https://idp/jwks"})
            claims_token = jwt.encode({"iss": "https://idp.example", "aud": "cid", "sub": "123", "nonce": "expected",
                                       "exp": 9999999999, "iat": 1}, key, algorithm="RS256")
            claims = adapter.validate_id_token(claims_token, nonce="expected", metadata={"jwks_uri": "x"})
            self.assertEqual(claims["sub"], "123")

    def test_no_password_is_stored(self):
        self.assertFalse(self.w.custodian.has_usable_password())


class ReferenceDataTests(TestCase):
    def setUp(self):
        self.w = World()

    def test_duplicate_codes_rejected(self):
        with self.assertRaises(ValidationFailed):
            ReferenceDataService.save(actor(self.w.admin), Location(code=self.w.loc.code, name="Dup", building="B"))

    def test_only_sysadmin_maintains_reference_data(self):
        with self.assertRaises(NotPermitted):
            ReferenceDataService.save(actor(self.w.custodian), Location(code="NEW1", name="New", building="B"))

    def test_deactivated_location_stays_in_history_and_cannot_be_selected(self):
        asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        ReferenceDataService.set_active(actor(self.w.admin), self.w.loc, False)
        asset.refresh_from_db()
        self.assertEqual(asset.location_id, self.w.loc.pk)  # history keeps it
        with self.assertRaises(ValidationFailed) as ctx:
            register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        self.assertIn("location", ctx.exception.field_errors)

    def test_reference_records_cannot_be_deleted(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.w.loc.delete()

    def test_role_grant_requires_department_scope(self):
        with self.assertRaises(ValidationFailed):
            RoleGrantService.grant(actor(self.w.admin), user=self.w.norole, role=Role.objects.get(code="CUSTODIAN"),
                                   department=None)

    def test_admin_screens_require_sysadmin(self):
        client = Client()
        sign_in(client, self.w.custodian)
        self.assertEqual(client.get("/identity/admin/departments/").status_code, 403)
        sign_in(client, self.w.admin)
        self.assertEqual(client.get("/identity/admin/departments/").status_code, 200)
        response = client.post("/identity/admin/departments/new/", {"code": "ENG", "name": "Duplicate"})
        self.assertEqual(response.status_code, 422)
