from django.core.management.base import BaseCommand
from django.utils import timezone
from exchange.models import Reservation
from exchange.services import ReservationService


class Command(BaseCommand):
    help = "Release expired uncommitted reservations. Run regularly from a supervised scheduler."

    def handle(self, *args, **options):
        rows = Reservation.objects.filter(state=Reservation.State.HELD, expires_at__lte=timezone.now()).select_related("approved_by")
        released = 0
        for row in rows.iterator():
            if ReservationService.expire(row.approved_by, row.pk):
                released += 1
        self.stdout.write(f"Released {released} expired hold(s).")
