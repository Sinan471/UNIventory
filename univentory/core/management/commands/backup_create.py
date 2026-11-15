from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand, CommandError

from core.backup import BackupError, create_backup


class Command(BaseCommand):
    help = "Create an encrypted backup of records and protected evidence; keep seven daily versions (NFR-17)."

    def add_arguments(self, parser):
        parser.add_argument("--generate-key", action="store_true",
                            help="Print a new encryption key for UNIVENTORY_BACKUP_KEY and exit.")

    def handle(self, *args, **options):
        if options["generate_key"]:
            self.stdout.write(Fernet.generate_key().decode())
            self.stderr.write("Store this key outside the application host (plan 7.4 step 2).")
            return
        try:
            path = create_backup()
        except BackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Encrypted backup written: {path}"))
