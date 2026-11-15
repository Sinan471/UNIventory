"""Settings for the automated test suite (SQLite, local fixtures)."""
import os
import tempfile

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DJANGO_DEBUG", "false")
_tmp = tempfile.mkdtemp(prefix="univentory-test-")
os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.join(_tmp, "dev.sqlite3").replace("\\", "/"))
os.environ.setdefault("UNIVENTORY_PROTECTED_MEDIA_ROOT", os.path.join(_tmp, "protected"))
os.environ.setdefault("UNIVENTORY_BACKUP_DIR", os.path.join(_tmp, "backups"))

from .settings import *  # noqa: E402,F401,F403

SECURE_SSL_REDIRECT = False
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# A file-backed test database lets the last-unit race test use real
# concurrent connections. With PostgreSQL, DATABASE_URL is used as normal.
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"]["TEST"] = {"NAME": os.path.join(_tmp, "test.sqlite3")}
