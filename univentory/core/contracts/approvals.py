"""Release-decision contract consumed by the catalogue.

Provider: Sinan's ApprovalService (workflow module). Consumer: Jesher's
CatalogueService. Listing publication asks this port for a *current*
release decision; the catalogue never records approvals itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ReleaseStatus:
    PENDING = "pending"
    APPROVED = "approved"
    RETURNED = "returned"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"

    CHOICES = [
        (PENDING, "Pending"),
        (APPROVED, "Approved"),
        (RETURNED, "Returned"),
        (REJECTED, "Rejected"),
        (SUPERSEDED, "Superseded"),
    ]


@dataclass(frozen=True)
class ReleaseDecision:
    case_ref: str
    status: str
    listing_id: int
    listing_version: int
    decided_by_id: int | None = None
    decided_at: datetime | None = None
    reason: str = ""
    is_test_adapter: bool = False

    def is_current_approval_for(self, listing_id: int, listing_version: int) -> bool:
        return (
            self.status == ReleaseStatus.APPROVED
            and self.listing_id == listing_id
            and self.listing_version == listing_version
        )


class ReleaseApprovalPort(Protocol):
    def request_release(self, *, listing, actor) -> str:
        """Open (or reuse) a release review case and return its reference."""

    def current_decision(self, *, listing) -> ReleaseDecision | None:
        """Return the latest decision for the listing (any version)."""

    def supersede(self, *, listing, actor, reason: str) -> None:
        """Supersede unexecuted release stages after a material change."""
