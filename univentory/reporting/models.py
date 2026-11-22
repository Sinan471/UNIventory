from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

class ReportSnapshot(models.Model):

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"

    title = models.CharField(max_length=200)

    description = models.TextField(blank=True)

    period_start = models.DateField()
    period_end = models.DateField()

    department = models.ForeignKey(
        "identity.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )

    data_snapshot = models.JSONField(default=dict)

    narrative_draft = models.TextField(blank=True)

    published_content = models.TextField(blank=True)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_reports"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    published_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.pk:
            original = ReportSnapshot.objects.filter(pk=self.pk).first()

            if (
                original
                and original.status == self.Status.PUBLISHED
            ):
                raise ValidationError(
                    "Published reports cannot be edited."
                )

        super().save(*args, **kwargs)


class SnapshotImpact(models.Model):

    snapshot = models.ForeignKey(
        ReportSnapshot,
        on_delete=models.CASCADE,
        related_name="impacts"
    )

    indicator = models.CharField(max_length=100)

    value = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        null=True,
        blank=True
    )

    unit = models.CharField(max_length=40)

    formula_version = models.CharField(max_length=40)

    source_evidence = models.JSONField(default=dict, blank=True)

    is_applicable = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.snapshot.title} - {self.indicator}"

def save(self, *args, **kwargs):
    if self.snapshot.status == ReportSnapshot.Status.PUBLISHED:
        raise ValidationError(
            "Impacts in published reports cannot be edited."
        )

    super().save(*args, **kwargs)


    def delete(self, *args, **kwargs):
        if self.snapshot.status == ReportSnapshot.Status.PUBLISHED:
            raise ValidationError(
                "Impacts in published reports cannot be deleted."
            )

        super().delete(*args, **kwargs)
