"""AccessPolicy: server-side role and scope decisions (FR-02, NFR-09, BR-01).

Owner: Jesher. Every module asks this class; nobody re-implements scope
checks. Grants are read from the database for each request (cached on the
user object for that request only), so a revocation applies to the next
protected operation, including inside an existing session (FR-03).

Hiding a button is never the control: views and services call these
methods at the endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from identity.models import Department, Role, UserRole

_CACHE_ATTR = "_univentory_grants"


@dataclass(frozen=True)
class Grant:
    role: str
    department_id: int | None  # None = campus-wide grant


class AccessPolicy:
    # ------------------------------------------------------------------
    # Grants
    # ------------------------------------------------------------------
    @staticmethod
    def grants(user) -> tuple[Grant, ...]:
        if user is None or not getattr(user, "is_authenticated", False) or not user.is_active:
            return ()
        cached = getattr(user, _CACHE_ATTR, None)
        if cached is not None:
            return cached
        rows = (
            UserRole.objects.active()
            .filter(user=user)
            .filter(Q(department__isnull=True) | Q(department__is_active=True))
            .values_list("role__code", "department_id")
        )
        result = tuple(Grant(role=code, department_id=dept) for code, dept in rows)
        setattr(user, _CACHE_ATTR, result)
        return result

    @staticmethod
    def refresh(user) -> None:
        if hasattr(user, _CACHE_ATTR):
            delattr(user, _CACHE_ATTR)

    @classmethod
    def role_codes(cls, user) -> set[str]:
        return {g.role for g in cls.grants(user)}

    @classmethod
    def has_any_role(cls, user) -> bool:
        return bool(cls.grants(user))

    @classmethod
    def has_role(cls, user, code: str, department=None) -> bool:
        dept_id = getattr(department, "pk", department)
        for grant in cls.grants(user):
            if grant.role != code:
                continue
            if dept_id is None or grant.department_id is None or grant.department_id == dept_id:
                return True
        return False

    @classmethod
    def departments_with_role(cls, user, code: str) -> list[int]:
        ids: set[int] = set()
        for grant in cls.grants(user):
            if grant.role != code:
                continue
            if grant.department_id is None:
                return list(Department.objects.active().values_list("pk", flat=True))
            ids.add(grant.department_id)
        return sorted(ids)

    # ------------------------------------------------------------------
    # Administration (system administrators have no business authority
    # unless separately assigned - BR-01)
    # ------------------------------------------------------------------
    @classmethod
    def is_sysadmin(cls, user) -> bool:
        return cls.has_role(user, Role.SYSADMIN)

    can_manage_reference_data = is_sysadmin
    can_manage_roles = is_sysadmin

    # ------------------------------------------------------------------
    # Catalogue
    # ------------------------------------------------------------------
    @classmethod
    def can_browse_catalogue(cls, user) -> bool:
        """Released catalogue summaries are visible across pilot departments."""
        return cls.has_any_role(user)

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------
    @classmethod
    def can_register_asset(cls, user, department=None) -> bool:
        return cls.has_role(user, Role.CUSTODIAN, department)

    @classmethod
    def registrable_departments(cls, user) -> list[int]:
        return cls.departments_with_role(user, Role.CUSTODIAN)

    @classmethod
    def can_edit_asset(cls, user, asset) -> bool:
        """Custodians edit only records assigned to them (FR-07)."""
        return asset.custodian_id == getattr(user, "pk", None) and cls.has_role(
            user, Role.CUSTODIAN, asset.department_id
        )

    @classmethod
    def asset_record_scope(cls, user) -> Q:
        """Q filter for Asset records whose private detail the user may read.

        Assigned custodian (of the record or of any active portion), or the
        Department Representative of the owning or holding department.
        """
        if not cls.has_any_role(user):
            return Q(pk__in=[])
        uid = user.pk
        scope = Q(custodian_id=uid) | Q(portions__custodian_id=uid, portions__is_active_leaf=True)
        rep_departments = cls.departments_with_role(user, Role.DEPT_REP)
        if rep_departments:
            scope |= Q(department_id__in=rep_departments)
            scope |= Q(portions__department_id__in=rep_departments, portions__is_active_leaf=True)
        return scope

    @classmethod
    def can_view_asset_record(cls, user, asset) -> bool:
        from inventory.models import Asset

        if not cls.has_any_role(user):
            return False
        return Asset.objects.filter(cls.asset_record_scope(user), pk=asset.pk).exists()

    can_view_restricted_evidence = can_view_asset_record

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------
    @classmethod
    def can_manage_listing(cls, user, listing) -> bool:
        return cls.can_edit_asset(user, listing.asset)
