"""Enable a synthetic receiver for the local development demonstration."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from identity.models import AppUser, Department, Role, UserRole


class Command(BaseCommand):
    help = "Give the synthetic Chemistry custodian a receiver role for local demonstrations."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo setup is available only in development mode.")
        try:
            user = AppUser.objects.get(username="omar.custodian", identity_issuer="dev-test")
            department = Department.objects.get(code="CHEM", is_active=True)
            role = Role.objects.get(code=Role.RECEIVER)
        except (AppUser.DoesNotExist, Department.DoesNotExist, Role.DoesNotExist) as exc:
            raise CommandError("Run seed_demo first to create the synthetic accounts and departments.") from exc
        UserRole.objects.get_or_create(user=user, role=role, department=department, revoked_at__isnull=True,
                                       defaults={"reason": "Synthetic local transfer demonstration"})
        self.stdout.write("Synthetic receiver ready: omar.custodian (Chemistry).")
