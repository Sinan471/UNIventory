
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce

from care.models import MaintenanceCase
from exchange.models import ReceiptEvent

from .models import (
    AvoidedPurchase,
    CohortOutcome,
    CostEntry,
    LifeExtensionEvidence,
    UnwantedCohort,
)


ZERO = Decimal("0")



class CostService:

    @staticmethod
    def calculate_savings():
        avoided = AvoidedPurchase.objects.filter(
            is_procurement_validated=True
        ).aggregate(
            total=Coalesce(Sum("baseline_value_aed"), ZERO)
        )["total"]

        costs = CostEntry.objects.filter(
            cost_type__in=[
                CostEntry.CostType.REPAIR,
                CostEntry.CostType.TRANSFER,
                CostEntry.CostType.REFURBISHMENT,
            ]
        ).aggregate(
            total=Coalesce(Sum("amount_aed"), ZERO)
        )["total"]

        return {
            "avoided_purchase_value_aed": avoided,
            "attributable_costs_aed": costs,
            "financial_savings_aed": avoided - costs,
        }


class ImpactCalculator:

    VERSION = "1.0"

    @staticmethod
    def reused_units():
        return ReceiptEvent.objects.aggregate(
            total=Coalesce(Sum("quantity"), ZERO)
        )["total"]

    @staticmethod
    def repair_outcomes():
        closed_jobs = MaintenanceCase.objects.filter(
            state=MaintenanceCase.State.CLOSED
        ).exclude(
            outcome="NO_REPAIR"
        )

        total = closed_jobs.count()

        successful = closed_jobs.filter(
            outcome="SUCCESS"
        ).count()

        if total == 0:
            return {
                "value": None,
                "successful_jobs": successful,
                "closed_jobs": total,
                "status": "NOT_APPLICABLE",
            }

        return {
            "value": Decimal(successful) / Decimal(total) * 100,
            "successful_jobs": successful,
            "closed_jobs": total,
            "status": "CALCULATED",
        }

    @staticmethod
    def waste_diversion():
        denominator = (
            UnwantedCohort.objects.aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )

        qualifying_outcomes = [
            CohortOutcome.Outcome.REUSE,
            CohortOutcome.Outcome.REPAIR_TO_USE,
            CohortOutcome.Outcome.REFURBISHMENT,
            CohortOutcome.Outcome.DONATION,
            CohortOutcome.Outcome.RECYCLING,
        ]

        numerator = (
            CohortOutcome.objects.filter(
                outcome__in=qualifying_outcomes
            ).aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )

        if denominator == ZERO:
            return {
                "status": "NOT_APPLICABLE",
                "value": None,
                "numerator": ZERO,
                "denominator": ZERO,
                "unit": "%",
            }

        return {
            "status": "CALCULATED",
            "value": (numerator / denominator) * Decimal("100"),
            "numerator": numerator,
            "denominator": denominator,
            "unit": "%",
        }
    @staticmethod
    def avoided_purchases():
        records = AvoidedPurchase.objects.filter(
            is_procurement_validated=True
        )

        return {
            "count": records.count(),
            "baseline_value_aed": records.aggregate(
                total=Coalesce(Sum("baseline_value_aed"), ZERO)
            )["total"],
        }

    @staticmethod
    def life_extension():
        records = LifeExtensionEvidence.objects.filter(
            verified_continued_use=True,
            verification_date__isnull=False,
        )

        extensions = []

        for record in records:
            days = (
                record.revised_retirement_date -
                record.baseline_retirement_date
            ).days

            extensions.append(days)

        if not extensions:
            return {
                "value": None,
                "verified_assets": 0,
                "status": "UNKNOWN",
            }

        return {
            "value": sum(extensions) / len(extensions),
            "verified_assets": len(extensions),
            "unit": "days",
            "status": "CALCULATED",
        }

    @staticmethod
    def carbon_reduction():
        """Estimated kg CO2e avoided by accepted reuse (SUS-08).

        Replacement emissions come from an active factor with activity
        ``replacement:<CATEGORY CODE>`` (kg CO2e per unit); reuse-side
        emissions from ``reuse:transfer`` (kg CO2e per moved unit). A receipt
        whose category has no replacement factor is left out and counted as
        uncovered; a missing transfer factor makes the whole result Unknown.
        Nothing missing is treated as zero.
        """
        from .models import EmissionFactor

        factors = {f.activity: f for f in EmissionFactor.objects.filter(is_active=True)}
        transfer = factors.get("reuse:transfer")
        if transfer is None:
            return {"value": None, "unit": "kg CO2e", "status": "UNKNOWN",
                    "note": "No reuse-side (transport) factor is recorded, so no estimate can be made."}
        total = ZERO
        covered = uncovered = ZERO
        sources = set()
        receipts = ReceiptEvent.objects.select_related("consignment__reservation__listing__asset__category")
        for receipt in receipts:
            code = receipt.consignment.reservation.listing.asset.category.code
            factor = factors.get(f"replacement:{code}")
            if factor is None:
                uncovered += receipt.quantity
                continue
            covered += receipt.quantity
            sources.update({factor.source_reference, transfer.source_reference})
            total += receipt.quantity * (factor.kg_co2e_per_unit - transfer.kg_co2e_per_unit)
        if covered == ZERO:
            return {"value": None, "unit": "kg CO2e", "status": "UNKNOWN",
                    "note": "No accepted reuse has a replacement factor for its category."}
        return {"value": total, "unit": "kg CO2e", "status": "ESTIMATED" if uncovered == ZERO else "PARTIAL_COVERAGE",
                "covered_units": covered, "uncovered_units": uncovered, "sources": sorted(sources),
                "note": "Estimate: replacement emissions minus transfer emissions for accepted units."}

    @classmethod
    def calculate_all(cls):
        return {
            "reused_units": {
                "value": cls.reused_units(),
                "status": "CALCULATED",
                "unit": "units",
            },
            "waste_diversion": cls.waste_diversion(),
            "avoided_purchases": cls.avoided_purchases(),
            "financial_savings": CostService.calculate_savings(),
            "repair_outcomes": cls.repair_outcomes(),
            "life_extension": cls.life_extension(),
            "carbon_reduction": cls.carbon_reduction(),
            "calculation_version": cls.VERSION,
        }


class CohortOutcomeService:

    @staticmethod
    @transaction.atomic
    def record_outcome(
        cohort_id,
        outcome,
        quantity,
        evidence_reference,
        recorded_by,
    ):
        cohort = UnwantedCohort.objects.select_for_update().get(
            pk=cohort_id
        )

        try:
            if isinstance(quantity, bool):
                raise InvalidOperation
            quantity = Decimal(str(quantity))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("Invalid outcome quantity.")

        if not quantity.is_finite() or quantity <= ZERO:
            raise ValidationError(
                "Quantity must be greater than zero."
            )

        if outcome not in CohortOutcome.Outcome.values:
            raise ValidationError("Invalid cohort outcome.")

        if not isinstance(evidence_reference, str) or not evidence_reference.strip():
            raise ValidationError("Evidence reference is required.")

        evidence_reference = evidence_reference.strip()

        if CohortOutcome.objects.filter(
            cohort=cohort,
            evidence_reference=evidence_reference,
        ).exists():
            raise ValidationError(
                "This evidence has already been recorded."
            )

        existing = (
            CohortOutcome.objects.filter(cohort=cohort)
            .aggregate(total=Sum("quantity"))["total"]
            or ZERO
        )

        if existing + quantity > cohort.quantity:
            raise ValidationError(
                "Outcome quantity exceeds the cohort quantity."
            )

        record = CohortOutcome(
            cohort=cohort,
            outcome=outcome,
            quantity=quantity,
            evidence_reference=evidence_reference,
            recorded_by=recorded_by,
        )

        record.full_clean()
        record.save()

        return record
