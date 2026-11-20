from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import WorkItem


class WorkDispatcher:
    MAX_ATTEMPTS = 5

    @staticmethod
    def schedule_hold_expiry(reservation):
        return WorkItem.objects.get_or_create(kind="expire_hold", object_id=reservation.pk, defaults={"due_at": reservation.expires_at})[0]

    @classmethod
    def run_one(cls, item_id):
        try:
            with transaction.atomic():
                item = WorkItem.objects.select_for_update().get(pk=item_id)
                if item.state != WorkItem.State.PENDING or item.due_at > timezone.now():
                    return False
                if item.kind == "expire_hold":
                    from exchange.models import Reservation
                    from exchange.services import ReservationService
                    reservation = Reservation.objects.select_related("approved_by").get(pk=item.object_id)
                    ReservationService.expire(reservation.approved_by, reservation.pk)
                else:
                    raise ValueError("Unknown work item kind")
                item.state, item.completed_at = WorkItem.State.COMPLETE, timezone.now()
                item.save(update_fields=["state", "completed_at"])
                return True
        except Exception as exc:
            with transaction.atomic():
                item = WorkItem.objects.select_for_update().get(pk=item_id)
                if item.state != WorkItem.State.PENDING:
                    return False
                item.attempts += 1
                item.last_error = f"{type(exc).__name__}: {exc}"[:500]
                if item.attempts >= cls.MAX_ATTEMPTS:
                    item.state = WorkItem.State.FAILED
                else:
                    item.due_at = timezone.now() + timedelta(seconds=min(60, 2 ** item.attempts))
                item.save(update_fields=["attempts", "last_error", "state", "due_at"])
            return False

    @classmethod
    def run_due(cls, limit=100):
        ids = list(WorkItem.objects.filter(state=WorkItem.State.PENDING, due_at__lte=timezone.now()).order_by("due_at", "pk").values_list("pk", flat=True)[:limit])
        return sum(cls.run_one(pk) for pk in ids)
