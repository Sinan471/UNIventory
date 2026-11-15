"""Listing (owner: Jesher). Catalogue publication record (FR-11 to FR-14)."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from identity.models import Department
from inventory.models import Asset, AssetPortion


class ListingState(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    AWAITING_RELEASE = "AWAITING_RELEASE", _("Awaiting release")
    PUBLISHED = "PUBLISHED", _("Published")
    PAUSED = "PAUSED", _("Paused")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")
    CLOSED = "CLOSED", _("Closed")

    @classmethod
    def open_states(cls):
        return [cls.DRAFT, cls.AWAITING_RELEASE, cls.PUBLISHED, cls.PAUSED]


class Listing(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="listings")
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="listings",
        help_text=_("Source department. Only its units of the asset are offered."),
    )
    portion = models.ForeignKey(
        AssetPortion, on_delete=models.PROTECT, related_name="listings",
        help_text=_("Portion the listing was prepared from (provenance)."),
    )
    title = models.CharField(_("listing title"), max_length=160)
    public_description = models.TextField(_("public description"))
    offered_quantity = models.DecimalField(
        _("offered quantity"), max_digits=12, decimal_places=3, validators=[MinValueValidator(0)]
    )
    collection_info = models.TextField(_("collection information"), help_text=_("Where and when it can be collected."))
    state = models.CharField(max_length=20, choices=ListingState.choices, default=ListingState.DRAFT)
    state_reason = models.CharField(max_length=255, blank=True)
    release_case_ref = models.CharField(max_length=64, blank=True)
    released_version = models.PositiveIntegerField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "department"],
                condition=Q(state__in=["DRAFT", "AWAITING_RELEASE", "PUBLISHED", "PAUSED"]),
                name="one_open_listing_per_asset_department",
            ),
            models.CheckConstraint(condition=Q(offered_quantity__gt=0), name="listing_offers_positive_quantity"),
        ]
        indexes = [models.Index(fields=["state", "published_at"])]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_state_display()})"

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Listings are withdrawn or closed, not deleted."))
