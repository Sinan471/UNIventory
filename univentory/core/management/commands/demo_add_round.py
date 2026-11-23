"""Stage the demo script's scenarios again, WITHOUT wiping the database.

DEVELOPMENT ONLY. After a presentation or rehearsal has used up the staged
work (published the desks, approved the centrifuge hold, inspected the
hotplate and so on), this adds a fresh copy of every live scenario so the
same demo script can be run again. Records from earlier runs stay, so the
Impact, Reports and Audit pages keep growing.

It uses the same module services as ``demo_reset``, so every new record has
its normal audit trail, ledger events and notifications.

    python manage.py demo_add_round            # one fresh round
    python manage.py demo_add_round --rounds 2 # two fresh rounds
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction

from core.contracts import get_adapter
from core.contracts.registry import reset_adapters

from .demo_reset import Command as DemoResetCommand


class Command(DemoResetCommand):
    help = "Add a fresh copy of the staged demo scenarios without wiping the database (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--rounds", type=int, default=1, help="How many fresh rounds to add (default 1, max 5).")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("demo_add_round only runs with DJANGO_DEBUG=true.")
        if not settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"):
            raise CommandError("demo_add_round only runs against the local SQLite database.")
        rounds = options["rounds"]
        if not 1 <= rounds <= 5:
            raise CommandError("--rounds must be between 1 and 5.")
        reset_adapters()
        for name in ("RELEASE_APPROVALS", "AUDIT"):
            if getattr(get_adapter(name), "is_test_adapter", True):
                raise CommandError(f"The {name} contract still uses a test adapter (see .env.example).")

        self._load()
        missing = [u for u in ("mariam.custodian", "khalid.rep", "sara.requester", "rashid.maint", "lina.haddad",
                               "ali.mahmoud") if u not in self.u]
        if missing:
            raise CommandError("Demo people are missing. Run `python manage.py demo_reset --yes` once first.")

        for n in range(rounds):
            with transaction.atomic():
                self._live_scenarios()
                self._recycling_proposal()
            self.stdout.write(f"  Round {n + 1} staged.")
        self.stdout.write(self.style.SUCCESS(
            "Fresh demo work added. Existing records were kept; the demo script can be run again."))
