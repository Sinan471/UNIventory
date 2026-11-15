from django.conf import settings
from django.db import models


class DefectReport(models.Model):
    asset = models.ForeignKey("inventory.Asset", on_delete=models.PROTECT, related_name="defects")
    portion = models.ForeignKey("inventory.AssetPortion", on_delete=models.PROTECT)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class MaintenanceCase(models.Model):
    class State(models.TextChoices):
        INSPECTION = "INSPECTION", "Under inspection"
        AWAITING_APPROVAL = "AWAITING_APPROVAL", "Awaiting work approval"
        IN_PROGRESS = "IN_PROGRESS", "Work in progress"
        VERIFY = "VERIFY", "Awaiting verification"
        CLOSED = "CLOSED", "Closed"

    defect = models.ForeignKey(DefectReport, on_delete=models.PROTECT, related_name="maintenance_cases")
    portion = models.ForeignKey("inventory.AssetPortion", on_delete=models.PROTECT)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    previous_case = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="rework")
    state = models.CharField(max_length=20, choices=State.choices, default=State.INSPECTION)
    inspection_notes = models.TextField(blank=True)
    work_notes = models.TextField(blank=True)
    outcome = models.CharField(max_length=20, blank=True)
    evidence = models.ForeignKey("inventory.Attachment", null=True, on_delete=models.PROTECT)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
