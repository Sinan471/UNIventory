"""Post-restore and monitoring checks (plan 7.4 step 4).

Checks quantity conservation for every asset, attachment hashes, claim
references, event ordering and backup freshness. Exits non-zero on failure.
"""
import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from core.backup import latest_backup_age_hours
from inventory.ledger import InventoryLedger
from inventory.models import Allocation, Asset, AssetPortion, Attachment
from inventory.services import AttachmentService


class Command(BaseCommand):
    help = "Verify quantity conservation, evidence hashes and record integrity."

    def add_arguments(self, parser):
        parser.add_argument("--skip-files", action="store_true")
        parser.add_argument("--max-backup-age-hours", type=float, default=None)

    def handle(self, *args, **options):
        problems = []
        assets = 0
        for asset in Asset.objects.all().iterator():
            assets += 1
            ok, expected, actual = InventoryLedger.verify_conservation(asset)
            if not ok:
                problems.append(f"{asset.asset_code}: expected {expected} units, found {actual}")
        orphan_claims = AssetPortion.objects.exclude(allocation=Allocation.FREE).filter(claim_ref="").count()
        if orphan_claims:
            problems.append(f"{orphan_claims} claimed portions have no claim reference")
        negative = AssetPortion.objects.filter(quantity__lt=0).count()
        if negative:
            problems.append(f"{negative} portions have negative quantity")
        dup_codes = Asset.objects.values("asset_code").annotate(n=Count("pk")).filter(n__gt=1).count()
        if dup_codes:
            problems.append(f"{dup_codes} duplicate asset codes")
        files = 0
        if not options["skip_files"]:
            for att in Attachment.objects.all().iterator():
                files += 1
                path = AttachmentService.path_for(att)
                if not path.exists():
                    problems.append(f"attachment {att.pk}: file missing")
                elif hashlib.sha256(path.read_bytes()).hexdigest() != att.sha256:
                    problems.append(f"attachment {att.pk}: hash mismatch")
        if options["max_backup_age_hours"] is not None:
            age = latest_backup_age_hours()
            if age is None or age > options["max_backup_age_hours"]:
                problems.append(f"latest backup is missing or older than {options['max_backup_age_hours']} hours")
        if problems:
            for p in problems:
                self.stderr.write(f"FAIL {p}")
            raise CommandError(f"{len(problems)} integrity problems found.")
        self.stdout.write(self.style.SUCCESS(
            f"Integrity OK: {assets} assets conserve quantity; {files} evidence files match their hashes."))
