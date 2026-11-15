"""Identity and reference data (owner: Jesher).

Entities from the Phase 4-5 data model: Department, AppUser, Role, UserRole,
Category and Location. Referenced entries are deactivated, never deleted
(FR-04, BR-17). No university password or Authenticator secret is stored
(NFR-08, DATA-06).
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

code_validator = RegexValidator(
    r"^[A-Z0-9][A-Z0-9_-]{1,31}$",
    _("Use 2-32 capital letters, digits, hyphens or underscores."),
)


class ReferenceQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class ReferenceRecord(models.Model):
    """Common behaviour for administrator-maintained reference data."""

    code = models.CharField(_("code"), max_length=32, unique=True, validators=[code_validator])
    name = models.CharField(_("name"), max_length=120)
    name_ar = models.CharField(_("Arabic name"), max_length=120, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ReferenceQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Reference records are deactivated, not deleted."))

    def display_name(self, language: str = "en") -> str:
        return self.name_ar if language == "ar" and self.name_ar else self.name


class Department(ReferenceRecord):
    class Meta(ReferenceRecord.Meta):
        verbose_name = _("department")


class Location(ReferenceRecord):
    """Physical place. Building/campus/site drive the matching location factor."""

    site = models.CharField(_("KU site"), max_length=80, default="Main Campus")
    campus = models.CharField(_("campus"), max_length=80, default="Main Campus")
    building = models.CharField(_("building"), max_length=80)
    room = models.CharField(_("room or area"), max_length=80, blank=True)
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="locations"
    )

    class Meta(ReferenceRecord.Meta):
        verbose_name = _("location")

    def __str__(self) -> str:
        return f"{self.name} ({self.building})"


class Category(ReferenceRecord):
    """Resource category with its typed specification schema (DATA-01).

    ``spec_schema`` is a list of ``{"key", "label", "type", "unit"}`` items.
    Supported types: text, integer, decimal, boolean.
    """

    ILLUSTRATIONS = [
        ("it", _("IT equipment")),
        ("furniture", _("Furniture")),
        ("lab", _("Laboratory equipment")),
        ("av", _("Audio-visual")),
        ("office", _("Office supplies")),
        ("tools", _("Tools and workshop")),
    ]

    description = models.TextField(_("description"), blank=True)
    subcategories = models.JSONField(_("subcategories"), default=list, blank=True)
    spec_schema = models.JSONField(_("specification fields"), default=list, blank=True)
    illustration = models.CharField(_("illustration"), max_length=16, choices=ILLUSTRATIONS, default="office")

    class Meta(ReferenceRecord.Meta):
        verbose_name = _("category")
        verbose_name_plural = _("categories")

    def clean(self):
        allowed = {"text", "integer", "decimal", "boolean"}
        keys = set()
        if not isinstance(self.spec_schema, list):
            raise ValidationError({"spec_schema": _("Specification fields must be a list.")})
        for item in self.spec_schema:
            if not isinstance(item, dict) or not item.get("key") or item.get("type") not in allowed:
                raise ValidationError({"spec_schema": _("Each field needs a key and a supported type.")})
            if item["key"] in keys:
                raise ValidationError({"spec_schema": _("Duplicate specification key %(key)s.") % item})
            keys.add(item["key"])


class Role(models.Model):
    """Application role. Roles are local authorisation data (IF-04)."""

    REQUESTER = "REQUESTER"
    DEPT_REP = "DEPT_REP"
    CUSTODIAN = "CUSTODIAN"
    RECEIVER = "RECEIVER"
    APPROVER = "APPROVER"
    MAINTENANCE = "MAINTENANCE"
    PROCUREMENT = "PROCUREMENT"
    FINANCE = "FINANCE"
    CAMPUS_USER = "CAMPUS_USER"
    SUSTAINABILITY = "SUSTAINABILITY"
    MANAGEMENT = "MANAGEMENT"
    AUDITOR = "AUDITOR"
    SYSADMIN = "SYSADMIN"
    REPORT_PUBLISHER = "REPORT_PUBLISHER"

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=80)
    name_ar = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    requires_department = models.BooleanField(
        default=True, help_text=_("Grants of this role must name a departmental scope.")
    )
    is_specialist = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Roles are part of the access matrix and cannot be deleted."))


class AppUserManager(BaseUserManager):
    use_in_migrations = True

    def get_or_provision(self, *, issuer: str, subject: str, email: str, display_name: str):
        """Return the local account for a verified university identity."""
        user, created = self.get_or_create(
            identity_issuer=issuer,
            identity_subject=subject,
            defaults={
                "username": (email or subject).lower()[:150],
                "email": email,
                "display_name": display_name or email or subject,
            },
        )
        changed = []
        if email and user.email != email:
            user.email = email
            changed.append("email")
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            changed.append("display_name")
        if created:
            user.set_unusable_password()
            user.save()
        elif changed:
            user.save(update_fields=changed)
        return user, created

    def create_user(self, username, **extra):
        user = self.model(username=username, **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user


class AppUser(AbstractBaseUser):
    """Local account bound to a stable university identity (DATA-06)."""

    username = models.CharField(_("username"), max_length=150, unique=True)
    email = models.EmailField(_("email"), blank=True)
    display_name = models.CharField(_("display name"), max_length=150)
    identity_issuer = models.CharField(max_length=255, default="dev-test")
    identity_subject = models.CharField(max_length=255)
    home_department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="members"
    )
    preferred_language = models.CharField(max_length=8, choices=settings.LANGUAGES, default="en")
    is_active = models.BooleanField(_("application access enabled"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppUserManager()

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["identity_issuer", "identity_subject"], name="unique_university_identity")
        ]
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name or self.username

    # Django expects these on user objects. No Django admin is installed;
    # these always answer False so no framework permission path exists.
    is_staff = False
    is_superuser = False

    def has_perm(self, perm, obj=None) -> bool:
        return False

    def has_module_perms(self, app_label) -> bool:
        return False

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Accounts are disabled, not deleted, to keep history."))


class UserRoleQuerySet(models.QuerySet):
    def active(self, at=None):
        at = at or timezone.now()
        return self.filter(revoked_at__isnull=True, effective_from__lte=at).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=at)
        )


class UserRole(models.Model):
    """Role grant with departmental scope and effective dates (FR-03)."""

    user = models.ForeignKey(AppUser, on_delete=models.PROTECT, related_name="role_grants")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="grants")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="role_grants"
    )
    effective_from = models.DateTimeField(default=timezone.now)
    effective_to = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(AppUser, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(AppUser, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=255, blank=True)

    objects = UserRoleQuerySet.as_manager()

    class Meta:
        ordering = ["user__display_name", "role__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "department"],
                condition=Q(revoked_at__isnull=True),
                name="one_open_grant_per_scope",
            )
        ]

    def __str__(self) -> str:
        scope = self.department.code if self.department_id else "campus"
        return f"{self.user} - {self.role.code} @ {scope}"

    def clean(self):
        if self.role_id and self.role.requires_department and not self.department_id:
            raise ValidationError({"department": _("This role needs a departmental scope.")})
        if self.department_id and not self.department.is_active and not self.pk:
            raise ValidationError({"department": _("Inactive departments cannot receive new grants.")})
        if self.effective_to and self.effective_to <= self.effective_from:
            raise ValidationError({"effective_to": _("The end must be after the start.")})

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Role grants are revoked, not deleted."))

    @property
    def is_active(self) -> bool:
        now = timezone.now()
        return (
            self.revoked_at is None
            and self.effective_from <= now
            and (self.effective_to is None or self.effective_to > now)
        )
