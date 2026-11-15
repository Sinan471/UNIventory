from django.conf import settings
from django.db import models
from django.db.models import Q


class Reservation(models.Model):
    class State(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        HELD = "HELD", "Held"
        COMMITTED = "COMMITTED", "Committed"
        EXPIRED = "EXPIRED", "Expired"
        REJECTED = "REJECTED", "Rejected"

    request = models.ForeignKey("demand.ResourceRequest", on_delete=models.PROTECT, related_name="reservations")
    listing = models.ForeignKey("catalogue.Listing", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    expires_at = models.DateTimeField(null=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="reservation_positive_quantity")]

    @property
    def claim_ref(self):
        return f"reservation:{self.pk}"


class Consignment(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.PROTECT, related_name="consignments")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assigned_consignments")
    destination = models.ForeignKey("identity.Location", on_delete=models.PROTECT)
    custodian = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_custody_consignments")
    dispatched_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    operation_key = models.CharField(max_length=64, unique=True, null=True)
    dispatched_at = models.DateTimeField(auto_now_add=True)

    @property
    def reference(self):
        return f"consignment:{self.pk}"


class ReceiptEvent(models.Model):
    consignment = models.ForeignKey(Consignment, on_delete=models.PROTECT, related_name="receipts")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    operation_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DiscrepancyResolution(models.Model):
    consignment = models.ForeignKey(Consignment, on_delete=models.PROTECT, related_name="resolutions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=[("RETURNED", "Physically returned"), ("LOST", "Lost")])
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
