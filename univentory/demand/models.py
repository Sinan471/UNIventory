from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class ResourceRequest(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Awaiting approval"
        APPROVED = "APPROVED", "Approved"
        PARTIAL = "PARTIAL", "Partially fulfilled"
        FULFILLED = "FULFILLED", "Fulfilled"
        RETURNED = "RETURNED", "Returned for revision"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="resource_requests")
    department = models.ForeignKey("identity.Department", on_delete=models.PROTECT)
    listing = models.ForeignKey("catalogue.Listing", null=True, blank=True, on_delete=models.PROTECT)
    title = models.CharField(max_length=160)
    # FR-15: category, minimum acceptable condition and destination of the need.
    category = models.ForeignKey("identity.Category", null=True, blank=True, on_delete=models.PROTECT,
                                 help_text="Helps matching. Required to submit.")
    min_condition = models.CharField("minimum acceptable condition", max_length=12, blank=True, default="",
                                     choices=[("", "Any condition"), ("POOR", "Poor"), ("FAIR", "Fair"),
                                              ("GOOD", "Good"), ("EXCELLENT", "Excellent")])
    destination = models.ForeignKey("identity.Location", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+", help_text="Where the items should be delivered.")
    purpose = models.TextField()
    specifications = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(0.001)])
    needed_by = models.DateField(null=True, blank=True)
    urgent = models.BooleanField(default=False)
    urgent_reason = models.TextField(blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="request_positive_quantity")]

    @property
    def accepted_quantity(self):
        from django.db.models import Sum
        from exchange.models import ReceiptEvent
        return ReceiptEvent.objects.filter(consignment__reservation__request=self).aggregate(total=Sum("quantity"))["total"] or 0

    @property
    def outstanding_quantity(self):
        return self.quantity - self.accepted_quantity


class RequestEvent(models.Model):
    request = models.ForeignKey(ResourceRequest, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=32)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "pk"]


class RequestOperation(models.Model):
    operation_key = models.CharField(max_length=64, unique=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    payload_hash = models.CharField(max_length=64)
    result = models.ForeignKey(ResourceRequest, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
