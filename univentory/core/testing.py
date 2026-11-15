"""Test factories shared by Jesher's module tests.

Other members may import these to build fixtures through the real services;
they create data only through public service methods.
"""
from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal

from django.db import transaction

from core.contracts import ActorContext, get_adapter
from core.contracts.approvals import ReleaseStatus
from identity.models import AppUser, Category, Department, Location, Role, UserRole
from inventory.ledger import InventoryLedger
from inventory.models import Lifecycle, SafetyState, TrackingType, Unit
from inventory.services import AssetInput, InventoryService

_counter = itertools.count(1)


def department(code=None, name=None) -> Department:
    n = next(_counter)
    return Department.objects.create(code=code or f"D{n}", name=name or f"Department {n}")


def location(dept=None, building="Building A", campus="Main Campus") -> Location:
    n = next(_counter)
    return Location.objects.create(code=f"L{n}", name=f"Room {n}", building=building, campus=campus,
                                   site=campus, department=dept)


def category(code=None, schema=None, subcategories=None) -> Category:
    n = next(_counter)
    return Category.objects.create(
        code=code or f"C{n}", name=f"Category {n}", illustration="it",
        spec_schema=schema if schema is not None else [
            {"key": "ram_gb", "label": "RAM", "type": "integer", "unit": "GB"},
            {"key": "model", "label": "Model", "type": "text"},
        ],
        subcategories=subcategories or [],
    )


def user(name=None, *grants) -> AppUser:
    """grants: (role_code, department_or_None) tuples."""
    n = next(_counter)
    username = name or f"user{n}"
    u = AppUser.objects.create_user(username, display_name=username.title(), email=f"{username}@example.invalid",
                                    identity_issuer="dev-test", identity_subject=f"dev-{username}")
    for role_code, dept in grants:
        UserRole.objects.create(user=u, role=Role.objects.get(code=role_code), department=dept)
    return u


def actor(u, key="") -> ActorContext:
    return ActorContext(user=u, operation_key=key)


def asset_input(dept, loc, cat, **overrides) -> AssetInput:
    data = dict(
        title="Dell Latitude laptop", description="14-inch laptop with charger.", category=cat, department=dept,
        location=loc, tracking_type=TrackingType.INDIVIDUAL, quantity=Decimal("1"), unit=Unit.EACH,
        acquisition_date=date(2022, 1, 10), estimated_value_aed=Decimal("2400.00"),
        specifications={"ram_gb": 16},
    )
    data.update(overrides)
    return AssetInput(**data)


def register(custodian, dept, loc, cat, *, cleared=True, state=Lifecycle.AVAILABLE, **overrides):
    with transaction.atomic():
        asset = InventoryService.register(actor(custodian), asset_input(dept, loc, cat, **overrides),
                                          activate_as=state)
        if cleared:
            portion = asset.portions.get(is_active_leaf=True)
            InventoryLedger.record_safety(actor(custodian), portion.pk, SafetyState.CLEARED,
                                          evidence_ref="test-clearance")
    asset.refresh_from_db()
    return asset


def batch(custodian, dept, loc, cat, quantity=10, **kw):
    kw.setdefault("title", "Stacking chairs")
    return register(custodian, dept, loc, cat, tracking_type=TrackingType.BATCH, quantity=Decimal(quantity),
                    specifications={}, **kw)


def approve_release(listing, rep):
    return get_adapter("RELEASE_APPROVALS").decide(listing=listing, decider=rep, status=ReleaseStatus.APPROVED)


class World:
    """A small campus: two departments with a custodian, rep and requester each."""

    def __init__(self):
        self.dept = department("ENG", "Engineering")
        self.other = department("SCI", "Science")
        self.loc = location(self.dept)
        self.other_loc = location(self.other, building="Building C")
        self.cat = category()
        self.custodian = user("custodian", (Role.CUSTODIAN, self.dept))
        self.custodian2 = user("custodian2", (Role.CUSTODIAN, self.dept))
        self.rep = user("rep", (Role.DEPT_REP, self.dept))
        self.requester = user("requester", (Role.REQUESTER, self.other))
        self.other_custodian = user("othercust", (Role.CUSTODIAN, self.other))
        self.admin = user("admin", (Role.SYSADMIN, None))
        self.norole = user("norole")
