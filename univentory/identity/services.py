"""Reference data and role-grant services (FR-03, FR-04)."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.utils import timezone

from core.contracts import NotPermitted, ValidationFailed
from core.contracts.audit import audit
from identity.models import AppUser, Department, Role, UserRole
from identity.policy import AccessPolicy


def _require_admin(actor) -> None:
    if not AccessPolicy.can_manage_reference_data(actor.user):
        raise NotPermitted()


def _as_validation_failed(exc: ValidationError) -> ValidationFailed:
    errors = exc.message_dict if hasattr(exc, "error_dict") else {"__all__": exc.messages}
    return ValidationFailed("Please correct the highlighted fields.", field_errors=errors)


class ReferenceDataService:
    """Maintain departments, locations and categories.

    Duplicate codes are rejected; referenced entries are deactivated, never
    deleted, and stay visible in history (FR-04).
    """

    @staticmethod
    @transaction.atomic
    def save(actor, instance):
        _require_admin(actor)
        before = {}
        if instance.pk:
            before = model_to_dict(type(instance).objects.get(pk=instance.pk))
        try:
            instance.full_clean()
            instance.save()
        except ValidationError as exc:
            raise _as_validation_failed(exc) from exc
        except IntegrityError as exc:
            raise ValidationFailed("That code is already in use.", field_errors={"code": ["Duplicate code."]}) from exc
        audit(
            "reference.created" if not before else "reference.updated",
            instance,
            actor,
            before=before,
            after=model_to_dict(instance),
        )
        return instance

    @staticmethod
    @transaction.atomic
    def set_active(actor, instance, active: bool, reason: str = ""):
        _require_admin(actor)
        if instance.is_active == active:
            return instance
        instance.is_active = active
        instance.save(update_fields=["is_active", "updated_at"])
        audit("reference.activated" if active else "reference.deactivated", instance, actor, reason=reason)
        return instance


class RoleGrantService:
    @staticmethod
    @transaction.atomic
    def grant(actor, *, user: AppUser, role: Role, department: Department | None, reason: str = "",
              effective_to=None) -> UserRole:
        if not AccessPolicy.can_manage_roles(actor.user):
            raise NotPermitted()
        grant = UserRole(
            user=user,
            role=role,
            department=department,
            granted_by=actor.user,
            reason=reason,
            effective_to=effective_to,
        )
        try:
            grant.full_clean(exclude=["granted_by"], validate_constraints=False)
            grant.save()
        except ValidationError as exc:
            raise _as_validation_failed(exc) from exc
        except IntegrityError as exc:
            raise ValidationFailed("This person already holds that role for that scope.") from exc
        audit("role.granted", grant, actor, after={"user": user.pk, "role": role.code,
                                                    "department": getattr(department, "pk", None)})
        return grant

    @staticmethod
    @transaction.atomic
    def revoke(actor, grant: UserRole, reason: str) -> UserRole:
        if not AccessPolicy.can_manage_roles(actor.user):
            raise NotPermitted()
        if not reason.strip():
            raise ValidationFailed("A reason is required.", field_errors={"reason": ["Required."]})
        grant = UserRole.objects.select_for_update().get(pk=grant.pk)
        if grant.revoked_at:
            return grant
        if grant.user_id == actor.user.pk and grant.role.code == Role.SYSADMIN:
            others = UserRole.objects.active().filter(role__code=Role.SYSADMIN).exclude(user=actor.user)
            if not others.exists():
                raise ValidationFailed("You cannot revoke the last active system administrator grant.")
        grant.revoked_at = timezone.now()
        grant.revoked_by = actor.user
        grant.reason = reason
        grant.save(update_fields=["revoked_at", "revoked_by", "reason"])
        audit("role.revoked", grant, actor, reason=reason)
        return grant

    @staticmethod
    @transaction.atomic
    def set_account_active(actor, user: AppUser, active: bool, reason: str) -> AppUser:
        if not AccessPolicy.can_manage_roles(actor.user):
            raise NotPermitted()
        if user.pk == actor.user.pk and not active:
            raise ValidationFailed("You cannot disable your own account.")
        user.is_active = active
        user.save(update_fields=["is_active"])
        audit("account.enabled" if active else "account.disabled", user, actor, reason=reason)
        return user
