
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
import uuid

class ModelVersion(models.Model):
    provider = models.CharField(max_length=80)
    model_name = models.CharField(max_length=120)
    version = models.CharField(max_length=40)
    supported_tasks = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    configuration = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "model_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "model_name", "version"],
                name="unique_ai_model_version"
            )
        ]

    def __str__(self):
        return f"{self.provider}: {self.model_name} ({self.version})"


class AIRun(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        TIMEOUT = "TIMEOUT", "Timed out"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    class TaskType(models.TextChoices):
        CLASSIFICATION = "CLASSIFICATION", "Classification"
        EMBEDDING = "EMBEDDING", "Embedding"
        MATCHING = "MATCHING", "Matching"
        ADVICE = "ADVICE", "Action advice"
        ASSISTANT = "ASSISTANT", "Assistant"
        REPORT = "REPORT", "Report narrative"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    model_version = models.ForeignKey(
        ModelVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="runs"
    )

    task_type = models.CharField(
        max_length=20,
        choices=TaskType.choices
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING
    )

    prompt_version = models.CharField(max_length=40, blank=True)
    schema_version = models.CharField(max_length=40, blank=True)
    ranking_version = models.CharField(max_length=40, blank=True)

    source_revisions = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)

    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)

    reserved_cost_aed = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
        validators=[MinValueValidator(0)]
    )

    actual_cost_aed = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=0,
        validators=[MinValueValidator(0)]
    )

    deadline = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    failure_code = models.CharField(max_length=60, blank=True)
    failure_message = models.TextField(blank=True)

    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["task_type", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.task_type} - {self.status}"

    def mark_running(self):
        self.status = self.Status.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at"])

    def mark_completed(self, result, input_tokens=0,
                       output_tokens=0, actual_cost_aed=0):
        self.status = self.Status.COMPLETED
        self.result = result
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.actual_cost_aed = actual_cost_aed
        self.completed_at = timezone.now()
        self.save()

    def mark_failed(self, code, message):
        self.status = self.Status.FAILED
        self.failure_code = code
        self.failure_message = message
        self.completed_at = timezone.now()
        self.save()

    
class MatchRecommendation(models.Model):
    comparison_set_id = models.UUIDField(
        default=uuid.uuid4,
        db_index=True,
        editable=False
    )

    request = models.ForeignKey(
        "demand.ResourceRequest",
        on_delete=models.PROTECT,
        related_name="match_recommendations",
        null=True,
        blank=True
    )

    listing = models.ForeignKey(
        "catalogue.Listing",
        on_delete=models.PROTECT,
        related_name="match_recommendations"
    )

    score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    factors = models.JSONField(default=dict, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    missing_evidence = models.JSONField(default=list, blank=True)

    ranking_version = models.CharField(max_length=40)
    source_revisions = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-score", "listing_id"]

    def __str__(self):
        return f"Recommendation for listing {self.listing_id}"


class RecommendationReview(models.Model):

    class Decision(models.TextChoices):
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        OVERRIDDEN = "OVERRIDDEN", "Overridden"

    recommendation = models.ForeignKey(
        MatchRecommendation,
        on_delete=models.PROTECT,
        related_name="reviews"
    )

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recommendation_reviews"
    )

    decision = models.CharField(
        max_length=12,
        choices=Decision.choices
    )

    overridden_listing = models.ForeignKey(
        "catalogue.Listing",
        on_delete=models.PROTECT,
        related_name="override_reviews",
        null=True,
        blank=True
    )

    reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.decision} - Recommendation {self.recommendation_id}"

