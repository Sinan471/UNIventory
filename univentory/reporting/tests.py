from datetime import date
from django.test import TestCase

from reporting.models import ReportSnapshot, SnapshotImpact
from reporting.services import (
    ReportingService,
    ReportPublicationService
)
from django.core.exceptions import ValidationError

class ReportingServiceTest(TestCase):

    def test_create_snapshot(self):
        snapshot = ReportingService.create_snapshot(
            title="Monthly Sustainability Report",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            data={"reused_units": 25}
        )

        self.assertEqual(snapshot.status, ReportSnapshot.Status.DRAFT)
        self.assertEqual(snapshot.data_snapshot["reused_units"], 25)

    def test_add_impact(self):
        snapshot = ReportingService.create_snapshot(
            title="Impact Report",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            data={}
        )

        impact = ReportingService.add_impact(
            snapshot,
            "Reused Units",
            25,
            "units"
        )

        self.assertEqual(impact.value, 25)

    def test_publish_report(self):
        snapshot = ReportingService.create_snapshot(
            title="Test Report",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            data={}
        )

        ReportPublicationService.publish(
            snapshot.pk,
            None,
            "This is a test report."
        )

        snapshot.refresh_from_db()

        self.assertEqual(
            snapshot.status,
            ReportSnapshot.Status.PUBLISHED
        )

    def test_cannot_publish_twice(self):
        snapshot = ReportingService.create_snapshot(
            title="Test Report",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            data={"total": 10},
        )

        ReportPublicationService.publish(
            snapshot.pk, None, "First publication"
        )

        with self.assertRaises(ValidationError):
            ReportPublicationService.publish(
                snapshot.pk, None, "Another publication"
            )

    def test_export_csv(self):
        from reporting.services import ReportingService

        snapshot = ReportingService.create_snapshot(
            title="Test Report",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            data={"total": 10},
        )

        ReportingService.add_impact(
            snapshot,
            "Reused Units",
            10,
            "units",
        )

        result = ReportingService.export_csv(snapshot.pk)

        self.assertIn("Test Report", result)
        self.assertIn("Reused Units", result)
        self.assertIn("units", result)

    def test_published_report_cannot_be_edited(self):
        from django.core.exceptions import ValidationError
        from reporting.services import ReportPublicationService

        snapshot = ReportingService.create_snapshot(
            title="Published Report",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            data={"total": 10},
        )

        ReportPublicationService.publish(
            snapshot.pk, None, "Final report"
        )

        snapshot.refresh_from_db()
        snapshot.title = "Changed title"

        with self.assertRaises(ValidationError):
            snapshot.save()

    def test_csv_export_url_exists(self):
        from django.urls import reverse

        url = reverse(
            "reporting:export_csv",
            kwargs={"snapshot_id": 1},
        )

        self.assertEqual(url, "/reporting/export/1/")
