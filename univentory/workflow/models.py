from django.conf import settings
from django.db import models


class ApprovalDecision(models.Model):
    request = models.ForeignKey("demand.ResourceRequest", on_delete=models.PROTECT, related_name="decisions")
    request_version = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20)
    reason = models.TextField(blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["decided_at", "pk"]


class ReleaseReview(models.Model):
    listing = models.ForeignKey("catalogue.Listing", on_delete=models.PROTECT, related_name="release_reviews")
    listing_version = models.PositiveIntegerField()
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=16, default="pending")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    decided_at = models.DateTimeField(null=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["listing", "listing_version"], name="release_review_listing_version")]
