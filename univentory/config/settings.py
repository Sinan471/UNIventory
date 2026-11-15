"""
UNIventory settings.

Owner: Jesher (S1 Platform and Access, S6 Operations).
Every secret and environment-specific value comes from the environment
(NFR-10). See ``.env.example`` for the full list.
"""

from pathlib import Path
import os
from urllib.parse import urlparse, unquote

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Minimal .env loader so local setup needs no extra dependency.

    Real environment variables always win over file values.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")


def env(name: str, default=None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise ImproperlyConfigured(f"Environment variable {name} is required.")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return str(env(name, str(default))).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-change-me" if DEBUG else None, required=not DEBUG)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

# ---------------------------------------------------------------------------
# Application composition. Jesher registers every module here (Section 8,
# "One Application and One UI System"). Sinan's and Jessica's apps are added
# to OPTIONAL_MODULES by their owners' requests once their packages exist.
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "identity",
    "inventory",
    "catalogue",
]

# Module packages owned by other members. They are installed automatically
# when present so the composition boundary stays in one place.
OPTIONAL_MODULES = [
    # Sinan
    "demand", "workflow", "exchange", "care", "final_actions",
    "audit", "notifications", "jobs",
    # Jessica
    "ai", "sustainability", "reporting",
]
for _module in OPTIONAL_MODULES:
    if (BASE_DIR / _module / "apps.py").exists():
        INSTALLED_APPS.append(_module)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "identity.middleware.ActorContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "core.context_processors.shell",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database. PostgreSQL (with pgvector for Jessica's ai module) is the
# documented production store. SQLite is accepted for local development and
# the automated test suite only.
# ---------------------------------------------------------------------------


def _database_from_url(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": 60,
            "ATOMIC_REQUESTS": False,
        }
    if parsed.scheme == "sqlite":
        name = unquote(parsed.path.lstrip("/")) or str(BASE_DIR / "db.sqlite3")
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": name,
            # IMMEDIATE serialises writers so locked stock operations behave
            # like row locks during local development.
            "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
        }
    raise ImproperlyConfigured(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")


DATABASES = {"default": _database_from_url(env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "identity.AppUser"

# ---------------------------------------------------------------------------
# Identity (FR-01, NFR-08, NFR-14)
# ---------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = ["identity.backends.UniversityIdentityBackend"]
LOGIN_URL = "identity:login"
LOGIN_REDIRECT_URL = "core:home"

UNIVENTORY_OIDC = {
    "ISSUER": env("KU_OIDC_ISSUER", ""),
    "CLIENT_ID": env("KU_OIDC_CLIENT_ID", ""),
    "CLIENT_SECRET": env("KU_OIDC_CLIENT_SECRET", ""),
    "REDIRECT_URI": env("KU_OIDC_REDIRECT_URI", ""),
    "SCOPES": env("KU_OIDC_SCOPES", "openid profile email"),
    "END_SESSION_REDIRECT": env("KU_OIDC_POST_LOGOUT_REDIRECT", ""),
    "TIMEOUT_SECONDS": 10,
}
# Development sign-in is a clearly labelled test adapter. It is refused
# outside DEBUG even if the flag is set.
UNIVENTORY_DEV_LOGIN = DEBUG and env_bool("UNIVENTORY_DEV_LOGIN", True)

SESSION_COOKIE_AGE = 30 * 60  # 30-minute inactivity limit (NFR-14)
SESSION_SAVE_EVERY_REQUEST = True  # sliding inactivity window
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # progressive JS reads the token for fetch()
CSRF_FAILURE_VIEW = "core.views.csrf_failure"

AUTH_PASSWORD_VALIDATORS = []  # no local passwords are stored (NFR-08)

# ---------------------------------------------------------------------------
# HTTPS and transport security (IF-08, NFR-10). Active whenever DEBUG is off.
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # Preload-list submission is a KU domain-wide decision, not this app's.
    SECURE_HSTS_PRELOAD = False
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Internationalisation (IF-08, FR-57)
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English")), ("ar", _("Arabic"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
TIME_ZONE = "Asia/Dubai"
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files and protected evidence storage
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(env("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))

# Evidence bytes never live under a public URL. Downloads go through
# inventory.views.attachment_download, which rechecks access (FR-08).
PROTECTED_MEDIA_ROOT = Path(env("UNIVENTORY_PROTECTED_MEDIA_ROOT", str(BASE_DIR / "protected_media")))
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

UNIVENTORY_ATTACHMENTS = {
    "MAX_BYTES": 10 * 1024 * 1024,
    "MAX_FILES_PER_RECORD": 10,
    "ALLOWED_TYPES": ["image/jpeg", "image/png", "application/pdf"],
}

# ---------------------------------------------------------------------------
# Backup and recovery (NFR-17)
# ---------------------------------------------------------------------------
UNIVENTORY_BACKUP = {
    "DIRECTORY": Path(env("UNIVENTORY_BACKUP_DIR", str(BASE_DIR / "backups"))),
    "ENCRYPTION_KEY": env("UNIVENTORY_BACKUP_KEY", ""),
    "RETAIN_DAILY_VERSIONS": 7,
}

# ---------------------------------------------------------------------------
# Contract adapters (Section 9). Each consumed interface is resolved by
# dotted path so the owning member can replace the labelled test adapter
# through configuration only.
# ---------------------------------------------------------------------------
UNIVENTORY_CONTRACT_ADAPTERS = {
    # Sinan's ApprovalService release decision for listings.
    "RELEASE_APPROVALS": env(
        "UNIVENTORY_RELEASE_APPROVALS_ADAPTER",
        "core.contracts.fixtures.FixtureReleaseApprovals",
    ),
    # Sinan's AuditService. The fixture writes structured log lines only.
    "AUDIT": env("UNIVENTORY_AUDIT_ADAPTER", "core.contracts.fixtures.LoggingAuditSink"),
}

UNIVENTORY_CATALOGUE_PAGE_SIZE = 24

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "univentory.audit": {"level": "INFO"},
        "django.security": {"level": "WARNING"},
    },
}
