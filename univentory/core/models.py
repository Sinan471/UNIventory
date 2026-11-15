"""Core records.

``FixtureReleaseDecision`` backs the labelled release-approval test adapter
in ``core.contracts.fixtures``. It is not part of the 38-entity data model and
must be removed once Sinan's ApprovalService is configured.
"""
from django.conf import settings
from django.db import models

from core.contracts.approvals import ReleaseStatus


class FixtureReleaseDecision(models.Model):
    listing_id = models.PositiveBigIntegerField(db_index=True)
    listing_version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=ReleaseStatus.CHOICES, default=ReleaseStatus.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "fixture release decision (test adapter)"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Fixture release {self.listing_id}v{self.listing_version}: {self.status}"
