from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Audit records cannot be modified.")

    def delete(self):
        raise ValidationError("Audit records cannot be deleted.")


class AuditLog(models.Model):
    objects = AppendOnlyQuerySet.as_manager()
    action = models.CharField(max_length=100, db_index=True)
    target_type = models.CharField(max_length=100, db_index=True)
    target_id = models.CharField(max_length=100, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    operation_key = models.CharField(max_length=64, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=20, default="success")
    reason = models.TextField(blank=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    target_version = models.PositiveIntegerField(null=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Audit records cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit records cannot be deleted.")
