from django.db import models


class WorkItem(models.Model):
    class State(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETE = "COMPLETE", "Complete"
        FAILED = "FAILED", "Failed"

    kind = models.CharField(max_length=40)
    object_id = models.PositiveBigIntegerField()
    due_at = models.DateTimeField(db_index=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "object_id"], name="unique_work_item")]
