
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from identity.models import Category, Department, Location
from inventory.models import Asset, AssetPortion, TrackingType, Unit
from sustainability.models import UnwantedCohort, CohortOutcome
from sustainability.services import ImpactCalculator, CohortOutcomeService

from sustainability.services import (
    ImpactCalculator,
    CohortOutcomeService,
    CostService
)

class CohortOutcomeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.user = User.objects.create_user(
            username="sustainability_test",
            password="test-password-123"
        )

        cls.department = Department.objects.create(name="Test Department")
        cls.category = Category.objects.create(name="Test Category")
        cls.location = Location.objects.create(
            name="Test Location",
            department=cls.department
        )

        cls.asset = Asset.objects.create(
            tracking_type=TrackingType.BATCH,
            title="Test chairs",
            description="Test asset",
            category=cls.category,
            registered_quantity=Decimal("10"),
            department=cls.department,
            custodian=cls.user,
            location=cls.location,
            created_by=cls.user
        )

        cls.portion = AssetPortion.objects.create(
            asset=cls.asset,
            quantity=Decimal("10"),
            department=cls.department,
            location=cls.location,
            custodian=cls.user
        )

    def setUp(self):
        self.cohort = UnwantedCohort.objects.create(
            asset=self.asset,
            portion=self.portion,
            quantity=Decimal("10"),
            evidence_reference="COHORT-TEST-001",
            recorded_by=self.user
        )

    def test_record_valid_reuse_outcome(self):
        outcome = CohortOutcomeService.record_outcome(
            self.cohort.pk,
            CohortOutcome.Outcome.REUSE,
            Decimal("4"),
            "REUSE-TEST-001",
            self.user
        )

        self.assertEqual(outcome.quantity, Decimal("4"))

    def test_outcome_cannot_exceed_cohort_quantity(self):
        with self.assertRaises(ValidationError):
            CohortOutcomeService.record_outcome(
                self.cohort.pk,
                CohortOutcome.Outcome.RECYCLING,
                Decimal("11"),
                "RECYCLE-TEST-001",
                self.user
            )

    def test_waste_diversion_percentage(self):
        CohortOutcomeService.record_outcome(
            self.cohort.pk,
            CohortOutcome.Outcome.REUSE,
            Decimal("4"),
            "REUSE-TEST-002",
            self.user
        )

        result = ImpactCalculator.waste_diversion()

        self.assertEqual(result["status"], "CALCULATED")
        self.assertEqual(result["value"], Decimal("40"))

    def test_zero_outcomes_produce_zero_diversion(self):
        result = ImpactCalculator.waste_diversion()

        self.assertEqual(result["status"], "CALCULATED")
        self.assertEqual(result["value"], Decimal("0"))
    def test_duplicate_evidence_is_rejected(self):
        CohortOutcomeService.record_outcome(
            self.cohort.pk,
            CohortOutcome.Outcome.REUSE,
            Decimal("2"),
            "DUPLICATE-TEST",
            self.user
        )

        with self.assertRaises(ValidationError):
            CohortOutcomeService.record_outcome(
                self.cohort.pk,
                CohortOutcome.Outcome.REUSE,
                Decimal("2"),
                "DUPLICATE-TEST",
                self.user
            )
    def test_financial_savings_can_be_negative(self):
        from sustainability.models import AvoidedPurchase, CostEntry

        AvoidedPurchase.objects.create(
            asset=self.asset,
            quantity=Decimal("2"),
            baseline_value_aed=Decimal("100.00"),
            procurement_reference="PROC-TEST-001",
            is_procurement_validated=True
        )

        CostEntry.objects.create(
            asset=self.asset,
            cost_type=CostEntry.CostType.REPAIR,
            amount_aed=Decimal("150.00"),
            description="Repair cost"
        )

        result = CostService.calculate_savings()

        self.assertEqual(
            result["financial_savings_aed"],
            Decimal("-50.00")
        )