"""Clearly labelled test adapters for interfaces owned by other members.

These exist so Jesher's modules can be built and demonstrated before Sinan's
ApprovalService and AuditService land (plan Section 16, "Managing
Dependencies Without Idle Time"). They are NOT the real workflow. The UI
shows a "Test adapter" badge wherever their output is displayed. Replace
them through ``UNIVENTORY_CONTRACT_ADAPTERS``; do not ship them in the final
demonstration.
"""
from __future__ import annotations

import json
import logging

from django.utils import timezone

from .approvals import ReleaseDecision, ReleaseStatus
from .audit import AuditEntry
from .errors import NotPermitted, ValidationFailed

audit_logger = logging.getLogger("univentory.audit")


class LoggingAuditSink:
    """Test adapter: writes structured audit lines to the log."""

    is_test_adapter = True

    def record(self, entry: AuditEntry) -> None:
        audit_logger.info("AUDIT %s", json.dumps(entry.__dict__, default=str, sort_keys=True))

    def record_denied(self, entry: AuditEntry) -> None:
        audit_logger.warning("AUDIT-DENIED %s", json.dumps(entry.__dict__, default=str, sort_keys=True))


class FixtureReleaseApprovals:
    """Test adapter for Sinan's release review.

    It applies the two rules the catalogue relies on so integration behaves
    realistically: the decider must hold an active Department Representative
    grant for the owning department, and cannot be the person who requested
    release (BR-02).
    """

    is_test_adapter = True

    def request_release(self, *, listing, actor) -> str:
        from core.models import FixtureReleaseDecision

        decision, _ = FixtureReleaseDecision.objects.get_or_create(
            listing_id=listing.pk,
            listing_version=listing.version,
            status=ReleaseStatus.PENDING,
            defaults={"requested_by": actor.user},
        )
        return f"fixture-release-{decision.pk}"

    def current_decision(self, *, listing) -> ReleaseDecision | None:
        from core.models import FixtureReleaseDecision

        row = (
            FixtureReleaseDecision.objects.filter(listing_id=listing.pk)
            .order_by("-listing_version", "-pk")
            .first()
        )
        if row is None:
            return None
        return ReleaseDecision(
            case_ref=f"fixture-release-{row.pk}",
            status=row.status,
            listing_id=row.listing_id,
            listing_version=row.listing_version,
            decided_by_id=row.decided_by_id,
            decided_at=row.decided_at,
            reason=row.reason,
            is_test_adapter=True,
        )

    def supersede(self, *, listing, actor, reason: str) -> None:
        from core.models import FixtureReleaseDecision

        FixtureReleaseDecision.objects.filter(
            listing_id=listing.pk, status__in=[ReleaseStatus.PENDING, ReleaseStatus.APPROVED]
        ).update(status=ReleaseStatus.SUPERSEDED, reason=reason)

    # -- fixture-only decision entry point (not part of the contract) -------
    def pending_for(self, user):
        """Listings awaiting a decision this user may give (fixture queue)."""
        from catalogue.models import Listing
        from core.models import FixtureReleaseDecision
        from identity.policy import AccessPolicy

        departments = AccessPolicy.departments_with_role(user, "DEPT_REP")
        pending_ids = FixtureReleaseDecision.objects.filter(status=ReleaseStatus.PENDING).values_list(
            "listing_id", flat=True
        )
        return (
            Listing.objects.filter(pk__in=pending_ids, asset__department__in=departments)
            .exclude(created_by=user)
            .select_related("asset", "asset__department")
        )

    def decide(self, *, listing, decider, status: str, reason: str = "") -> ReleaseDecision:
        from core.models import FixtureReleaseDecision
        from identity.policy import AccessPolicy

        row = FixtureReleaseDecision.objects.filter(
            listing_id=listing.pk, listing_version=listing.version, status=ReleaseStatus.PENDING
        ).first()
        if row is None:
            raise ValidationFailed("There is no pending release review for the current listing version.")
        if row.requested_by_id == decider.pk or listing.created_by_id == decider.pk:
            raise NotPermitted("A proposer cannot approve their own release (BR-02).")
        if not AccessPolicy.has_role(decider, "DEPT_REP", department=listing.asset.department):
            raise NotPermitted("Only the owning Department Representative can decide release.")
        if status not in {ReleaseStatus.APPROVED, ReleaseStatus.RETURNED, ReleaseStatus.REJECTED}:
            raise ValidationFailed("Unknown decision.")
        if status != ReleaseStatus.APPROVED and not reason.strip():
            raise ValidationFailed("A reason is required to return or reject.", field_errors={"reason": ["Required."]})
        row.status = status
        row.decided_by = decider
        row.decided_at = timezone.now()
        row.reason = reason
        row.save(update_fields=["status", "decided_by", "decided_at", "reason"])
        return self.current_decision(listing=listing)
