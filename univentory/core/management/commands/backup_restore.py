from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.backup import BackupError, restore_backup


class Command(BaseCommand):
    help = ("Decrypt a backup into an EMPTY isolated directory and verify file hashes. "
            "It never overwrites the live database; follow docs/RECOVERY.md to promote it.")

    def add_arguments(self, parser):
        parser.add_argument("archive")
        parser.add_argument("--target", required=True, help="Empty directory for the isolated restore.")

    def handle(self, *args, **options):
        try:
            meta = restore_backup(Path(options["archive"]), Path(options["target"]))
        except BackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Restored snapshot {meta['created_utc']} to {options['target']}: "
            f"{len(meta['attachments'])} attachments verified, database file {meta['database_file']}."
        ))
        if meta.get("missing_files"):
            self.stdout.write(self.style.WARNING(f"{len(meta['missing_files'])} files were missing at backup time."))
        self.stdout.write("Next: point DATABASE_URL and UNIVENTORY_PROTECTED_MEDIA_ROOT at the restored copy "
                          "and run `manage.py integrity_check` before reopening (docs/RECOVERY.md).")
