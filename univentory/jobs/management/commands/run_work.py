from django.core.management.base import BaseCommand
from jobs.services import WorkDispatcher


class Command(BaseCommand):
    help = "Process due work once; run regularly using a supervised scheduler."

    def handle(self, *args, **options):
        self.stdout.write(f"Completed {WorkDispatcher.run_due()} work item(s).")
