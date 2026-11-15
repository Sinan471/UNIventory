from django.db import transaction
from django.utils import timezone
from core.contracts.approvals import ReleaseDecision, ReleaseStatus
from core.contracts.errors import NotPermitted, StaleVersion, ValidationFailed
from identity.models import Role
from identity.policy import AccessPolicy
from .models import ReleaseReview


class ReleaseApprovals:
    is_test_adapter = False

    def request_release(self, *, listing, actor):
        row, _ = ReleaseReview.objects.get_or_create(listing=listing, listing_version=listing.version,
                                                      defaults={"requested_by": actor.user})
        return f"release-{row.pk}"

    def current_decision(self, *, listing):
        row = ReleaseReview.objects.filter(listing=listing).order_by("-listing_version", "-pk").first()
        if row is None:
            return None
        return ReleaseDecision(case_ref=f"release-{row.pk}", status=row.status, listing_id=row.listing_id,
            listing_version=row.listing_version, decided_by_id=row.decided_by_id, decided_at=row.decided_at,
            reason=row.reason, is_test_adapter=False)

    def supersede(self, *, listing, actor, reason):
        ReleaseReview.objects.filter(listing=listing, status__in=[ReleaseStatus.PENDING, ReleaseStatus.APPROVED]).update(
            status=ReleaseStatus.SUPERSEDED, reason=reason)

    @transaction.atomic
    def decide(self, *, decider, status, reason="", listing_id=None, expected_version=None, listing=None):
        from catalogue.models import Listing
        if listing is not None:
            listing_id, expected_version = listing.pk, listing.version
        if listing_id is None or expected_version is None:
            raise ValidationFailed("The listing and reviewed version are required.")
        listing = Listing.objects.select_for_update().select_related("asset").get(pk=listing_id)
        if listing.version != expected_version:
            raise StaleVersion("This listing changed. Reload it before reviewing.")
        row = ReleaseReview.objects.select_for_update().filter(listing=listing, listing_version=listing.version,
                                                                 status=ReleaseStatus.PENDING).first()
        if not row:
            raise ValidationFailed("There is no pending review for this listing version.")
        if not AccessPolicy.has_role(decider, Role.DEPT_REP, listing.department_id):
            raise NotPermitted("Only the source department representative can review this listing.")
        if decider.pk in (row.requested_by_id, listing.created_by_id):
            raise NotPermitted("You cannot review your own release request.")
        if status not in (ReleaseStatus.APPROVED, ReleaseStatus.RETURNED, ReleaseStatus.REJECTED):
            raise ValidationFailed("Choose a valid decision.")
        if status != ReleaseStatus.APPROVED and not reason.strip():
            raise ValidationFailed("A reason is required to return or reject.")
        row.status, row.decided_by, row.decided_at, row.reason = status, decider, timezone.now(), reason.strip()
        row.save(update_fields=["status", "decided_by", "decided_at", "reason"])
        from core.contracts.audit import audit
        from core.contracts import ActorContext
        audit("listing.release_decision", listing, ActorContext(decider), after={"decision": status}, reason=reason)
        return self.current_decision(listing=listing)
