
import csv
from io import StringIO

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ReportSnapshot, SnapshotImpact


class ReportingService:

    @staticmethod
    def create_snapshot(
        title, period_start, period_end, data,
        user=None, department=None
    ):
        if period_end < period_start:
            raise ValidationError("End date cannot be before start date.")

        if not isinstance(data, dict):
            raise ValidationError("Snapshot data must be a dictionary.")

        if not title or not title.strip():
            raise ValidationError("A report title is required.")

        return ReportSnapshot.objects.create(
            title=title,
            period_start=period_start,
            period_end=period_end,
            data_snapshot=data,
            created_by=user,
            department=department,
        )

    @staticmethod
    def add_impact(
        snapshot, indicator, value, unit,
        formula_version="1.0", source_evidence=None
    ):
        if snapshot.status != ReportSnapshot.Status.DRAFT:
            raise ValidationError("Published reports cannot be changed.")

        if not indicator or not unit:
            raise ValidationError("Indicator and unit are required.")

        return SnapshotImpact.objects.create(
            snapshot=snapshot,
            indicator=indicator,
            value=value,
            unit=unit,
            formula_version=formula_version,
            source_evidence=source_evidence or {},
        )

    @staticmethod
    def export_csv(snapshot_id):
        try:
            snapshot = ReportSnapshot.objects.get(pk=snapshot_id)
        except ReportSnapshot.DoesNotExist:
            raise ValidationError("Report snapshot does not exist.")

        output = StringIO()
        writer = csv.writer(output)

        writer.writerow(["Report Title", snapshot.title])
        writer.writerow(["Period Start", snapshot.period_start])
        writer.writerow(["Period End", snapshot.period_end])
        writer.writerow(["Department", snapshot.department_id or "All"])
        writer.writerow([])

        writer.writerow([
            "Indicator", "Value", "Unit",
            "Formula Version", "Applicable", "Source Evidence"
        ])

        for impact in snapshot.impacts.all().order_by("indicator"):
            writer.writerow([
                impact.indicator,
                impact.value if impact.value is not None else "Unknown",
                impact.unit,
                impact.formula_version,
                impact.is_applicable,
                impact.source_evidence,
            ])

        return output.getvalue()


class ReportPublicationService:

    @staticmethod
    @transaction.atomic
    def publish(snapshot_id, user, content):
        try:
            snapshot = ReportSnapshot.objects.select_for_update().get(
                pk=snapshot_id
            )
        except ReportSnapshot.DoesNotExist:
            raise ValidationError("Report snapshot does not exist.")

        if snapshot.status != ReportSnapshot.Status.DRAFT:
            raise ValidationError("This report has already been published.")

        if not content or not content.strip():
            raise ValidationError("Published content cannot be empty.")

        if not isinstance(snapshot.data_snapshot, dict):
            raise ValidationError("Invalid report data snapshot.")

        if snapshot.period_end < snapshot.period_start:
            raise ValidationError("Invalid report period.")

        snapshot.published_content = content.strip()
        snapshot.status = ReportSnapshot.Status.PUBLISHED
        snapshot.published_by = user
        snapshot.published_at = timezone.now()
        snapshot.save()

        return snapshot
