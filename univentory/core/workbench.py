"""Workbench: what is waiting on the signed-in person (owner: Jesher).

Read-only. Every count and item is derived from the same server-side scope
rules the owning module enforces (AccessPolicy departments, assignment and
the no-self-approval rule), so nothing here reveals a record the person
cannot open. The home page shows the items as cards; the rail shows totals.

Modules owned by other members are consumed through their models only for
reads, and each block is skipped when the module is not installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.apps import apps
from django.db.models import Q, Sum
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext as _

from identity.models import Role
from identity.policy import AccessPolicy

ITEMS_PER_TASK = 4


@dataclass
class Task:
    key: str
    title: str
    detail: str
    count: int
    url: str
    icon: str
    nav: str  # navigation key whose counter includes this task
    action: str = ""
    items: list = field(default_factory=list)

    @property
    def waiting(self) -> bool:
        return self.count > 0


def _url(name: str, *args) -> str:
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ""


def _installed(label: str) -> bool:
    return apps.is_installed(label)


def q(value) -> str:
    """Quantity without trailing zeros: 1, 2.5."""
    return format(Decimal(value).normalize(), "f")


def _item(title, url, sub=""):
    return {"title": title, "url": url, "sub": sub}


def _task(out, key, title, detail, rows, url, icon, nav, action, make):
    rows = list(rows)
    out.append(Task(key, title, detail, len(rows), url, icon, nav, action,
                    [make(r) for r in rows[:ITEMS_PER_TASK]]))


def tasks_for(user) -> list[Task]:
    if not AccessPolicy.has_any_role(user):
        return []
    codes = AccessPolicy.role_codes(user)
    reps = AccessPolicy.departments_with_role(user, Role.DEPT_REP)
    custodian_depts = AccessPolicy.departments_with_role(user, Role.CUSTODIAN)
    receiver_depts = AccessPolicy.departments_with_role(user, Role.RECEIVER)
    requester_depts = AccessPolicy.departments_with_role(user, Role.REQUESTER)
    maintenance = AccessPolicy.departments_with_role(user, Role.MAINTENANCE)
    out: list[Task] = []

    # ---- Department representative: independent decisions -----------------
    if reps and _installed("demand") and _installed("workflow"):
        from demand.models import ResourceRequest
        from workflow.models import ReleaseReview

        rows = (ResourceRequest.objects.filter(department_id__in=reps, state=ResourceRequest.State.SUBMITTED)
                .exclude(requester=user).select_related("department", "requester").order_by("-urgent", "needed_by"))
        _task(out, "needs", _("Needs to approve"), _("Requests from your departments"), rows, _url("workflow:queue"),
              "clipboard", "approvals", _("Review need"),
              lambda r: _item(r.title, _url("workflow:review", r.pk), f"{r.requester.display_name}, {r.department.code}"))
        rows = (ReleaseReview.objects.filter(listing__department_id__in=reps, status="pending")
                .exclude(requested_by=user).exclude(listing__created_by=user).select_related("listing", "listing__department"))
        _task(out, "releases", _("Listings to release"), _("Surplus waiting to go on the exchange"), rows,
              _url("workflow:queue") + "#releases", "tag", "approvals", _("Release"),
              lambda r: _item(r.listing.title, _url("workflow:release_review", r.pk), r.listing.department.name))
    if reps and _installed("exchange"):
        from exchange.models import Reservation

        rows = (Reservation.objects.filter(listing__department_id__in=reps, state=Reservation.State.PENDING)
                .exclude(requested_by=user).select_related("listing", "request__department"))
        _task(out, "holds", _("Holds to approve"), _("Reservations on your stock"), rows, _url("transfer:queue"),
              "lock", "transfers", _("Approve hold"),
              lambda r: _item(r.listing.title, _url("transfer:detail", r.pk), f"{q(r.quantity)} for {r.request.department.code}"))
        rows = (Reservation.objects.filter(request__department_id__in=reps, state=Reservation.State.HELD)
                .exclude(requested_by=user).select_related("listing", "request__department"))
        _task(out, "transfers", _("Transfers to approve"), _("Held items coming into your departments"), rows,
              _url("transfer:queue"), "truck", "transfers", _("Approve transfer"),
              lambda r: _item(r.listing.title, _url("transfer:detail", r.pk), f"{q(r.quantity)} to {r.request.department.code}"))
    if reps and _installed("care"):
        from care.models import MaintenanceCase

        rows = (MaintenanceCase.objects.filter(portion__department_id__in=reps, state=MaintenanceCase.State.AWAITING_APPROVAL)
                .exclude(Q(opened_by=user) | Q(technician=user)).select_related("defect__asset"))
        _task(out, "work", _("Repairs to approve"), _("Maintenance spend waiting for you"), rows, _url("care:list"),
              "wrench", "care", _("Approve work"),
              lambda c: _item(c.defect.asset.title, _url("care:case", c.pk), _("Repair plan")))
    if reps and _installed("final_actions"):
        from final_actions.models import FinalAction

        rows = (FinalAction.objects.filter(department_id__in=reps, state=FinalAction.State.PROPOSED)
                .exclude(proposed_by=user).select_related("asset"))
        _task(out, "finals", _("Final actions to approve"), _("Donation, recycling or disposal"), rows,
              _url("final_actions:list"), "recycle", "final_actions", _("Approve"),
              lambda f: _item(f.asset.title, _url("final_actions:detail", f.pk), f"{f.outcome.title()}, {q(f.quantity)}"))

    # ---- Custodian: inventory work --------------------------------------
    if custodian_depts:
        from catalogue.models import Listing, ListingState
        from core.contracts import get_adapter

        port = get_adapter("RELEASE_APPROVALS")
        ready = []
        for listing in Listing.objects.filter(asset__custodian=user, department_id__in=custodian_depts,
                                              state=ListingState.AWAITING_RELEASE):
            decision = port.current_decision(listing=listing)
            if decision and decision.status == "approved" and decision.listing_version == listing.version:
                ready.append(listing)
        _task(out, "publish", _("Ready to publish"), _("Released listings you can put on the exchange"), ready,
              _url("inventory:my_assets"), "send", "assets", _("Publish"),
              lambda l: _item(l.title, _url("catalogue:listing_detail", l.pk), _("Released")))
        rows = Listing.objects.filter(asset__custodian=user, department_id__in=custodian_depts, state=ListingState.DRAFT)
        _task(out, "drafts", _("Draft listings"), _("Not yet sent for release"), rows, _url("inventory:my_assets"),
              "edit", "assets", _("Finish"), lambda l: _item(l.title, _url("catalogue:listing_detail", l.pk), _("Draft")))
        if _installed("exchange"):
            from exchange.models import Reservation

            rows = []
            for row in (Reservation.objects.filter(state=Reservation.State.COMMITTED, listing__asset__custodian=user,
                                                   listing__department_id__in=custodian_depts)
                        .select_related("listing", "request__department")):
                sent = row.consignments.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
                if sent < row.quantity:
                    rows.append(row)
            _task(out, "dispatch", _("Ready to dispatch"), _("Approved transfers to hand over"), rows,
                  _url("transfer:queue"), "truck", "transfers", _("Dispatch"),
                  lambda r: _item(r.listing.title, _url("transfer:detail", r.pk), f"{q(r.quantity)} to {r.request.department.code}"))
        if _installed("final_actions"):
            from final_actions.models import FinalAction

            rows = (FinalAction.objects.filter(asset__custodian=user, department_id__in=custodian_depts,
                                               state__in=[FinalAction.State.APPROVED, FinalAction.State.IN_PROGRESS])
                    .select_related("asset"))
            _task(out, "execute", _("Final actions to complete"), _("Approved outcomes needing evidence"), rows,
                  _url("final_actions:list"), "recycle", "final_actions", _("Record"),
                  lambda f: _item(f.asset.title, _url("final_actions:detail", f.pk), f.outcome.title()))

    # ---- Receiver -------------------------------------------------------
    if receiver_depts and _installed("exchange"):
        from exchange.models import Consignment

        rows = []
        for shipment in (Consignment.objects.filter(receiver=user, reservation__request__department_id__in=receiver_depts)
                         .select_related("reservation__listing")):
            done = (shipment.receipts.aggregate(total=Sum("quantity"))["total"] or Decimal(0)) + (
                shipment.resolutions.aggregate(total=Sum("quantity"))["total"] or Decimal(0))
            if done < shipment.quantity:
                shipment.outstanding = shipment.quantity - done
                rows.append(shipment)
        _task(out, "receive", _("Deliveries to confirm"), _("Items on their way to you"), rows,
              _url("transfer:queue"), "inbox", "transfers", _("Confirm receipt"),
              lambda c: _item(c.reservation.listing.title, _url("transfer:receipt", c.pk), f"{q(c.outstanding)} arriving"))

    # ---- Requester ------------------------------------------------------
    if requester_depts and _installed("demand"):
        from demand.models import ResourceRequest

        mine = ResourceRequest.objects.filter(requester=user, department_id__in=requester_depts)
        rows = mine.filter(state__in=[ResourceRequest.State.DRAFT, ResourceRequest.State.RETURNED])
        _task(out, "my_drafts", _("Requests to finish"), _("Drafts and returned requests"), rows, _url("demand:list"),
              "edit", "requests", _("Finish"), lambda r: _item(r.title, _url("demand:detail", r.pk), r.get_state_display()))
        approved = mine.filter(state__in=[ResourceRequest.State.APPROVED, ResourceRequest.State.PARTIAL])
        if _installed("exchange"):
            from exchange.models import Reservation

            approved = approved.exclude(reservations__state__in=[
                Reservation.State.PENDING, Reservation.State.HELD, Reservation.State.COMMITTED])
        _task(out, "reserve", _("Ready to reserve"), _("Approved needs without a reservation"), approved.distinct(),
              _url("demand:list"), "check-circle", "requests", _("Reserve"),
              lambda r: _item(r.title, _url("demand:detail", r.pk), _("Approved")))

    # ---- Maintenance ----------------------------------------------------
    if maintenance and _installed("care"):
        from care.models import DefectReport, MaintenanceCase

        rows = (DefectReport.objects.filter(portion__department_id__in=maintenance)
                .exclude(maintenance_cases__isnull=False).select_related("asset"))
        _task(out, "inspect", _("Defects to inspect"), _("Reported problems"), rows, _url("care:list"),
              "alert", "care", _("Inspect"), lambda d: _item(d.asset.title, _url("care:inspect", d.pk), d.description[:48]))
        cases = MaintenanceCase.objects.filter(portion__department_id__in=maintenance).select_related("defect__asset")
        rows = cases.filter(Q(state=MaintenanceCase.State.INSPECTION) | Q(state=MaintenanceCase.State.IN_PROGRESS, technician=user))
        _task(out, "service", _("Jobs in progress"), _("Inspections and repairs to finish"), rows, _url("care:list"),
              "wrench", "care", _("Continue"), lambda c: _item(c.defect.asset.title, _url("care:case", c.pk), c.get_state_display()))
        rows = cases.filter(state=MaintenanceCase.State.VERIFY).exclude(technician=user)
        _task(out, "verify", _("Repairs to verify"), _("Independent check of finished work"), rows, _url("care:list"),
              "shield", "care", _("Verify"), lambda c: _item(c.defect.asset.title, _url("care:case", c.pk), _("Work finished")))

    # ---- Oversight roles -----------------------------------------------
    if codes & {Role.SUSTAINABILITY, Role.MANAGEMENT, Role.PROCUREMENT, Role.FINANCE, Role.REPORT_PUBLISHER} or reps:
        if _url("sustainability:impact"):
            out.append(Task("impact", _("Impact"), _("Reuse, savings and diversion"), 0, _url("sustainability:impact"),
                            "leaf", "impact"))
        if _url("reporting:index"):
            out.append(Task("reports", _("Reports"), _("Requests and transfers, CSV"), 0, _url("reporting:index"),
                            "bar-chart", "reports"))
    if Role.AUDITOR in codes and _url("audit:list"):
        out.append(Task("audit", _("Audit history"), _("Search and export the event log"), 0, _url("audit:list"),
                        "history", "audit"))
    if Role.SYSADMIN in codes:
        out.append(Task("admin", _("Administration"), _("People, roles and reference data"), 0,
                        _url("identity:admin_home"), "settings", "admin"))
    return out


def nav_counts(tasks: list[Task]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task.nav] = counts.get(task.nav, 0) + task.count
    return counts


def unread_notifications(user) -> int:
    if not _installed("notifications") or not getattr(user, "is_authenticated", False):
        return 0
    from notifications.models import Notification

    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
