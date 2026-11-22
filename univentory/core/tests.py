"""Platform tests: backup/restore, integrity check, shell, contracts and deployment settings."""
import io
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings

from core.backup import BackupError, create_backup, prune, restore_backup
from core.contracts import ActorContext
from core.testing import World, actor, register
from identity.tests import sign_in
from inventory.models import AttachmentAccess
from inventory.services import AttachmentService


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class BackupTests(TestCase):
    def setUp(self):
        self.w = World()
        self.asset = register(self.w.custodian, self.w.dept, self.w.loc, self.w.cat)
        AttachmentService.store(actor(self.w.custodian), self.asset, SimpleUploadedFile("p.png", _png()),
                                access_class=AttachmentAccess.CATALOGUE_PHOTO)
        self.tmp = tempfile.mkdtemp()
        self.key = Fernet.generate_key().decode()

    def settings_for(self):
        return override_settings(UNIVENTORY_BACKUP={"DIRECTORY": Path(self.tmp) / "out", "ENCRYPTION_KEY": self.key,
                                                    "RETAIN_DAILY_VERSIONS": 7})

    def test_round_trip_is_encrypted_and_verified(self):
        with self.settings_for():
            archive = create_backup()
            raw = archive.read_bytes()
            self.assertNotIn(b"SQLite format", raw)  # encrypted at rest
            meta = restore_backup(archive, Path(self.tmp) / "restore")
            self.assertEqual(len(meta["attachments"]), 1)
            self.assertTrue((Path(self.tmp) / "restore" / meta["database_file"]).exists())

    def test_wrong_key_cannot_restore(self):
        with self.settings_for():
            archive = create_backup()
        with override_settings(UNIVENTORY_BACKUP={"DIRECTORY": Path(self.tmp), "ENCRYPTION_KEY": Fernet.generate_key().decode(),
                                                  "RETAIN_DAILY_VERSIONS": 7}):
            with self.assertRaises(BackupError):
                restore_backup(archive, Path(self.tmp) / "restore2")

    def test_missing_key_refuses_backup(self):
        with override_settings(UNIVENTORY_BACKUP={"DIRECTORY": Path(self.tmp), "ENCRYPTION_KEY": "",
                                                  "RETAIN_DAILY_VERSIONS": 7}):
            with self.assertRaises(BackupError):
                create_backup()

    def test_retains_seven_versions(self):
        out = Path(self.tmp) / "keep"
        out.mkdir()
        for day in range(1, 10):
            (out / f"univentory-backup-202611{day:02d}T000000Z.tar.gz.enc").write_bytes(b"x")
        with self.settings_for():
            prune(out)
        self.assertEqual(len(list(out.iterdir())), 7)

    def test_integrity_check_passes_and_detects_tampering(self):
        call_command("integrity_check", stdout=io.StringIO())
        att = self.asset.attachments.get()
        AttachmentService.path_for(att).write_bytes(b"tampered")
        with self.assertRaises(CommandError):
            call_command("integrity_check", stdout=io.StringIO(), stderr=io.StringIO())


class ShellTests(TestCase):
    def setUp(self):
        self.w = World()

    def test_navigation_follows_role(self):
        client = Client()
        sign_in(client, self.w.custodian)
        page = client.get("/exchange/").content.decode()
        self.assertIn("My Assets", page)
        self.assertNotIn("Administration", page)
        sign_in(client, self.w.requester)
        page = client.get("/exchange/").content.decode()
        self.assertNotIn("My Assets", page)
        self.assertIn("Exchange", page)

    def test_first_screen_per_role(self):
        """Every role lands on a workbench listing only its own work."""
        client = Client()
        sign_in(client, self.w.custodian)
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Draft listings")
        self.assertNotContains(page, "Needs to approve")
        sign_in(client, self.w.requester)
        page = client.get("/")
        self.assertContains(page, "Requests to finish")
        self.assertNotContains(page, "Ready to dispatch")
        sign_in(client, self.w.admin)
        page = client.get("/")
        self.assertContains(page, "/identity/admin/")
        self.assertNotContains(page, "Needs to approve")

    def test_test_adapter_banner_is_visible(self):
        client = Client()
        sign_in(client, self.w.custodian)
        self.assertContains(client.get("/exchange/"), "Integration test adapters active")

    def test_arabic_layout_is_rtl(self):
        client = Client()
        sign_in(client, self.w.requester)
        client.cookies["django_language"] = "ar"
        page = client.get("/exchange/").content.decode()
        self.assertIn('dir="rtl"', page)
        self.assertIn('lang="ar"', page)

    def test_health_endpoint_has_no_business_data(self):
        response = Client().get("/healthz/")
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_operation_key_hash_is_stable(self):
        self.assertEqual(ActorContext.payload_hash({"a": 1, "b": 2}), ActorContext.payload_hash({"b": 2, "a": 1}))


class DeploymentSettingsTests(TestCase):
    def test_production_security_settings(self):
        """NFR-10 / IF-08: with DEBUG off, HTTPS and secure cookies are enforced."""
        from django.conf import settings

        self.assertFalse(settings.DEBUG)
        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        self.assertTrue(settings.CSRF_COOKIE_SECURE)
        self.assertGreaterEqual(settings.SECURE_HSTS_SECONDS, 31536000)
        self.assertFalse(settings.UNIVENTORY_DEV_LOGIN)


class TranslationCompilerTests(TestCase):
    def test_po_round_trip_with_plurals(self):
        import gettext

        from core.management.commands.compile_translations import parse_po, write_mo

        po = ('msgid ""\nmsgstr "Content-Type: text/plain; charset=UTF-8\\n"\n\n'
              'msgid "Exchange"\nmsgstr "التبادل"\n\n'
              'msgid "%(n)s item"\nmsgid_plural "%(n)s items"\nmsgstr[0] "a"\nmsgstr[1] "b"\n')
        path = Path(tempfile.mkdtemp()) / "t.mo"
        write_mo(parse_po(po), path)
        with open(path, "rb") as handle:
            catalogue = gettext.GNUTranslations(handle)
        self.assertEqual(catalogue.gettext("Exchange"), "التبادل")
