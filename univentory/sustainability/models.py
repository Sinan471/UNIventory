from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

class CostEntry(models.Model):

    class CostType(models.TextChoices):
        PURCHASE = "PURCHASE", "Purchase"
        REPAIR = "REPAIR", "Repair"
        TRANSFER = "TRANSFER", "Transfer"
        REFURBISHMENT = "REFURBISHMENT", "Refurbishment"

    asset = models.ForeignKey(
        "inventory.Asset",
        on_delete=models.PROTECT,
        related_name="sustainability_costs"
    )

    cost_type = models.CharField(
        max_length=20,
        choices=CostType.choices
    )

    amount_aed = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    description = models.TextField(blank=True)

    evidence_reference = models.CharField(max_length=255, blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.asset.asset_code} - {self.cost_type}"


class AvoidedPurchase(models.Model):

    asset = models.ForeignKey(
        "inventory.Asset",
        on_delete=models.PROTECT,
        related_name="avoided_purchases"
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(0)]
    )

    baseline_value_aed = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    procurement_reference = models.CharField(max_length=255)

    is_procurement_validated = models.BooleanField(default=False)

    validated_at = models.DateTimeField(null=True, blank=True)

    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Avoided purchase - {self.asset.asset_code}"


class SustainabilityImpact(models.Model):

    asset = models.ForeignKey(
        "inventory.Asset",
        on_delete=models.PROTECT,
        related_name="sustainability_impacts"
    )

    reused_units = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0
    )

    waste_diversion_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0
    )

    financial_savings_aed = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    carbon_reduction_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True
    )

    calculation_version = models.CharField(
        max_length=40,
        default="1.0"
    )

    source_evidence = models.JSONField(default=dict, blank=True)

    calculated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Impact - {self.asset.asset_code}"

class UnwantedCohort(models.Model):
    """Records units entering the unwanted-asset measurement cohort."""

    asset = models.ForeignKey(
        "inventory.Asset",
        on_delete=models.PROTECT,
        related_name="unwanted_cohorts"
    )

    portion = models.ForeignKey(
        "inventory.AssetPortion",
        on_delete=models.PROTECT,
        related_name="unwanted_cohorts"
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(0.001)]
    )

    entered_at = models.DateTimeField(default=timezone.now)

    evidence_reference = models.CharField(max_length=255)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    def __str__(self):
        return f"Cohort - {self.asset.asset_code}"


class LifeExtensionEvidence(models.Model):
    asset = models.ForeignKey(
        "inventory.Asset",
        on_delete=models.PROTECT,
        related_name="life_extension_evidence"
    )

    baseline_retirement_date = models.DateField()

    revised_retirement_date = models.DateField()

    verified_continued_use = models.BooleanField(default=False)

    verification_date = models.DateField(null=True, blank=True)

    evidence_reference = models.CharField(max_length=255)

    recorded_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.revised_retirement_date <= self.baseline_retirement_date:
            raise ValidationError(
                "The revised retirement date must be later than the baseline."
            )

        if self.verified_continued_use and not self.verification_date:
            raise ValidationError(
                "A verification date is required for continued use."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        
class EmissionFactor(models.Model):
    name = models.CharField(max_length=150)

    activity = models.CharField(max_length=100)

    kg_co2e_per_unit = models.DecimalField(
        max_digits=14,
        decimal_places=6,
        validators=[MinValueValidator(0)]
    )

    unit = models.CharField(max_length=40)

    source_reference = models.CharField(max_length=255)

    version = models.CharField(max_length=40)

    valid_from = models.DateField()

    valid_until = models.DateField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} - {self.version}"

class CohortOutcome(models.Model):
    class Outcome(models.TextChoices):
        REUSE = "REUSE", "Reuse"
        REPAIR_TO_USE = "REPAIR_TO_USE", "Repair to use"
        REFURBISHMENT = "REFURBISHMENT", "Refurbishment"
        DONATION = "DONATION", "Donation"
        RECYCLING = "RECYCLING", "Recycling"
        DISPOSAL = "DISPOSAL", "Disposal"

    cohort = models.ForeignKey(
        UnwantedCohort,
        on_delete=models.PROTECT,
        related_name="outcomes"
    )
    outcome = models.CharField(max_length=25, choices=Outcome.choices)
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(0.001)]
    )
    evidence_reference = models.CharField(max_length=255)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cohort", "outcome", "evidence_reference"],
                name="unique_cohort_outcome_evidence"
            )
        ]

    def __str__(self):
        return f"{self.cohort_id} - {self.outcome}"