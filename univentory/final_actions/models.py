from django.conf import settings
from django.db import models


class FinalAction(models.Model):
    class State(models.TextChoices):
        PROPOSED = "PROPOSED", "Awaiting approval"
        APPROVED = "APPROVED", "Approved"
        IN_PROGRESS = "IN_PROGRESS", "Partially executed"
        COMPLETED = "COMPLETED", "Completed"

    asset = models.ForeignKey("inventory.Asset", on_delete=models.PROTECT)
    portion = models.ForeignKey("inventory.AssetPortion", on_delete=models.PROTECT)
    department = models.ForeignKey("identity.Department", on_delete=models.PROTECT)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    outcome = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.TextField()
    recipient = models.CharField(max_length=200, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PROPOSED)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def claim_ref(self):
        return f"final:{self.pk}"


class FinalActionExecution(models.Model):
    action = models.ForeignKey(FinalAction, on_delete=models.PROTECT, related_name="executions")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    evidence = models.ForeignKey("inventory.Attachment", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation_key = models.CharField(max_length=64, unique=True)
    executed_at = models.DateTimeField(auto_now_add=True)
