"""Rebuild the local demonstration database with staged, labelled scenarios.

DEVELOPMENT ONLY. Refuses to run unless DEBUG is on and the database is
SQLite. Wipes the local database and protected files, re-seeds the roles,
the reference data and a synthetic catalogue (``seed_demo``), adds one
persona per documented role, and then drives every staged scenario through
the real module services (DemandService, ApprovalService, ReservationService,
TransferService, CareService, FinalActionService). Nothing is written with a
raw state edit, so every scenario carries its normal audit trail, ledger
events and notifications.

Every record is synthetic. Totals shown on the Impact page after a reset
demonstrate that the calculations work; they are not KU results.

    python manage.py demo_reset --yes
"""
from __future__ import annotations

import importlib
import shutil
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.contracts import ActorContext, get_adapter
from core.contracts.registry import reset_adapters
from core.contracts.approvals import ReleaseStatus

# A minimal, valid one-page PDF used as synthetic evidence (receipts,
# certificates, verification sheets). The text says it is synthetic.
SYNTHETIC_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 120]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 58>>stream\nBT /F1 12 Tf 20 60 Td (Synthetic demo evidence - not real) Tj ET\nendstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

PERSONAS = [
    # One sign-in person per job (dev-test issuer, shown on the sign-in page).
    ("rashid.maint", "Rashid Al Nuaimi", [("MAINTENANCE", "MECH"), ("MAINTENANCE", "CHEM"), ("MAINTENANCE", "FAC")]),
    ("reem.sustain", "Reem Al Ketbi", [("SUSTAINABILITY", None), ("REPORT_PUBLISHER", None), ("PROCUREMENT", None),
                                       ("FINANCE", None), ("MANAGEMENT", None)]),
    ("salma.auditor", "Salma Yousuf", [("AUDITOR", None)]),
]
# Colleagues who appear in the records (history, second signatures) but cannot
# sign in: their identity issuer is neither the KU IdP nor the dev adapter.
STAFF_ISSUER = "ku-staff-synthetic"
STAFF = [
    ("ali.mahmoud", "Ali Mahmoud", [("REQUESTER", "MECH"), ("RECEIVER", "MECH")]),
    ("dana.yousef", "Dana Yousef", [("REQUESTER", "FAC"), ("RECEIVER", "FAC")]),
    ("lina.haddad", "Lina Haddad", [("MAINTENANCE", "MECH"), ("MAINTENANCE", "CHEM"), ("MAINTENANCE", "FAC")]),
]


class Command(BaseCommand):
    help = "Wipe the local SQLite database and rebuild the staged demonstration (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm that the local database will be wiped.")
        parser.add_argument("--assets", type=int, default=60, help="Background catalogue size (default 60).")

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("demo_reset only runs with DJANGO_DEBUG=true.")
        if not settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"):
            raise CommandError("demo_reset only runs against the local SQLite database.")
        if not options["yes"]:
            raise CommandError("This wipes the local database. Re-run with --yes to continue.")
        reset_adapters()
        for name in ("RELEASE_APPROVALS", "AUDIT"):
            if getattr(get_adapter(name), "is_test_adapter", True):
                raise CommandError(
                    f"The {name} contract still uses a test adapter. Set UNIVENTORY_RELEASE_APPROVALS_ADAPTER="
                    "workflow.adapters.ReleaseApprovals and UNIVENTORY_AUDIT_ADAPTER=audit.services.AuditService "
                    "(see .env.example)."
                )

        self.stdout.write("Wiping local database and protected files...")
        call_command("migrate", verbosity=0)
        call_command("flush", interactive=False, verbosity=0)
        shutil.rmtree(settings.PROTECTED_MEDIA_ROOT, ignore_errors=True)
        seed_roles = importlib.import_module("identity.migrations.0002_seed_roles")
        from django.apps import apps as global_apps

        seed_roles.seed(global_apps, None)

        self.stdout.write("Seeding reference data and background catalogue...")
        call_command("seed_demo", assets=options["assets"], verbosity=0)
        self._personas()
        self._load()
        self.stdout.write("Staging scenarios through the module services...")
        self._stage()
        self.stdout.write(self.style.SUCCESS(
            "Demo ready. Run `python manage.py runserver` and open http://127.0.0.1:8000/ . "
            "See DEMO_GUIDE.md for the walkthrough."
        ))

    # ------------------------------------------------------------------
    def _personas(self):
        from identity.models import AppUser, Department, Role, UserRole

        roles = {r.code: r for r in Role.objects.all()}
        depts = {d.code: d for d in Department.objects.all()}
        for issuer, people in (("dev-test", PERSONAS), (STAFF_ISSUER, STAFF)):
            for username, display, grants in people:
                user, created = AppUser.objects.get_or_create(username=username, defaults={
                    "display_name": display, "email": f"{username}@example.invalid",
                    "identity_issuer": issuer, "identity_subject": f"{issuer}-{username}"})
                if created:
                    user.set_unusable_password()
                    user.save()
                for role, dept in grants:
                    UserRole.objects.get_or_create(user=user, role=roles[role],
                                                   department=depts.get(dept) if dept else None,
                                                   revoked_at=None, defaults={"reason": "Synthetic demo grant"})

    def _load(self):
        from identity.models import AppUser, Category, Department, Location

        self.u = {u.username: u for u in AppUser.objects.all()}
        self.d = {d.code: d for d in Department.objects.all()}
        self.c = {c.code: c for c in Category.objects.all()}
        self.loc = {loc.code: loc for loc in Location.objects.all()}

    # ------------------------------------------------------------------
    # Small wrappers around the real services
    # ------------------------------------------------------------------
    @staticmethod
    def _key():
        return uuid.uuid4().hex

    def _asset(self, custodian, dept, cat, loc, title, description, quantity, *, condition="GOOD", value=None,
               specs=None, state="AVAILABLE", clear=True, years=3):
        from inventory.ledger import InventoryLedger
        from inventory.models import SafetyState, TrackingType, Unit
        from inventory.services import AssetInput, InventoryService

        actor = ActorContext(user=self.u[custodian])
        qty = Decimal(quantity)
        with transaction.atomic():
            asset = InventoryService.register(actor, AssetInput(
                title=title, description=description, category=self.c[cat], department=self.d[dept],
                location=self.loc[loc], tracking_type=TrackingType.BATCH if qty > 1 else TrackingType.INDIVIDUAL,
                quantity=qty, unit=Unit.EACH, condition=condition, tags=[cat.lower(), "demo"],
                acquisition_date=timezone.localdate() - timedelta(days=365 * years),
                estimated_value_aed=Decimal(value) if value is not None else None,
                estimated_value_unknown=value is None, specifications=specs or {}, provenance="SYNTHETIC",
            ), activate_as=state)
            if clear:
                portion = asset.portions.filter(is_active_leaf=True).first()
                InventoryLedger.record_safety(actor, portion.pk, SafetyState.CLEARED, evidence_ref="synthetic-seed-clearance")
        return asset

    def _listing(self, asset, custodian, *, release_by=None, publish=True):
        from catalogue.services import CatalogueService

        actor = ActorContext(user=self.u[custodian])
        portion = asset.portions.filter(is_active_leaf=True).first()
        listing = CatalogueService.create(
            actor, asset=asset, title=asset.title, public_description=asset.description,
            offered_quantity=portion.quantity,
            collection_info=f"{portion.location.building}, {portion.location.name}. Sun-Thu 08:00-15:00.")
        listing = CatalogueService.transition(actor, listing.pk, "submit", expected_version=listing.version)
        if release_by:
            get_adapter("RELEASE_APPROVALS").decide(listing=listing, decider=self.u[release_by],
                                                     status=ReleaseStatus.APPROVED)
            if publish:
                listing = CatalogueService.transition(actor, listing.pk, "publish", expected_version=listing.version)
        listing.refresh_from_db()
        return listing

    def _need(self, requester, dept, title, purpose, quantity, listing=None, *, submit=True, urgent=False, reason="",
              specs="", days=21):
        from demand.services import DemandService

        from identity.models import Location

        category = listing.asset.category if listing else self.c["IT"]
        destination = Location.objects.filter(department=self.d[dept]).order_by("code").first()
        data = {"department": self.d[dept], "title": title, "purpose": purpose, "specifications": specs,
                "category": category, "destination": destination, "min_condition": "",
                "quantity": Decimal(quantity), "needed_by": timezone.localdate() + timedelta(days=days),
                "urgent": urgent, "urgent_reason": reason}
        return DemandService.save(self.u[requester], data, listing=listing, submit=submit, operation_key=self._key())

    def _approve_need(self, rep, need):
        from workflow.services import ApprovalService

        need.refresh_from_db()
        return ApprovalService.decide_request(self.u[rep], need.pk, need.version, "approve")

    def _reserve(self, requester, need, listing, quantity):
        from exchange.services import ReservationService

        return ReservationService.request(self.u[requester], need.pk, listing.pk, Decimal(quantity))

    def _hold(self, rep, reservation):
        from exchange.services import ReservationService

        reservation.refresh_from_db()
        return ReservationService.approve(self.u[rep], reservation.pk, reservation.version)

    def _commit(self, rep, reservation):
        from exchange.services import ReservationService

        reservation.refresh_from_db()
        return ReservationService.commit(self.u[rep], reservation.pk, reservation.version)

    def _dispatch(self, custodian, reservation, quantity, receiver, loc, dest_custodian):
        from exchange.services import TransferService

        return TransferService.dispatch(self.u[custodian], reservation.pk, Decimal(quantity), self.u[receiver],
                                        self.loc[loc], self.u[dest_custodian], self._key())

    def _receive(self, receiver, consignment, quantity):
        from exchange.services import TransferService

        return TransferService.receive(self.u[receiver], consignment.pk, Decimal(quantity), self._key())

    def _evidence(self, asset, custodian, name, description):
        from inventory.models import AttachmentAccess
        from inventory.services import AttachmentService

        upload = SimpleUploadedFile(name, SYNTHETIC_PDF, content_type="application/pdf")
        return AttachmentService.store(ActorContext(user=self.u[custodian]), asset, upload,
                                       access_class=AttachmentAccess.RESTRICTED, description=description)

    def _portion(self, asset):
        return asset.portions.filter(is_active_leaf=True).order_by("pk").first()

    # ------------------------------------------------------------------
    def _flow(self, requester, dept, listing, qty, title, purpose, *, receive=None, urgent=False, reason=""):
        """Run one request through need, hold, transfer, dispatch and (optional) receipt."""
        need = self._need(requester, dept, title, purpose, qty, listing, urgent=urgent, reason=reason)
        self._approve_need("khalid.rep", need)
        res = self._reserve(requester, need, listing, qty)
        self._hold("khalid.rep", res)
        self._commit("khalid.rep", res)
        dest = self._dest(dept)
        cons = self._dispatch("mariam.custodian", res, qty, requester, dest, "mariam.custodian")
        if receive:
            self._receive(requester, cons, receive)
        return need, res, cons

    def _dest(self, dept):
        from identity.models import Location

        return Location.objects.filter(department=self.d[dept]).order_by("code").first().code

    def _backdate(self, need, when, since):
        """Move one completed history case to a past date (charts need a real time spread)."""
        from datetime import timedelta as td

        from demand.models import RequestEvent, ResourceRequest
        from exchange.models import Consignment, ReceiptEvent, Reservation
        from notifications.models import Notification
        from workflow.models import ApprovalDecision

        ResourceRequest.objects.filter(pk=need.pk).update(created_at=when, updated_at=when + td(days=5))
        RequestEvent.objects.filter(request=need).update(occurred_at=when + td(hours=2))
        ApprovalDecision.objects.filter(request=need).update(decided_at=when + td(hours=6))
        Reservation.objects.filter(request=need).update(created_at=when + td(days=1))
        Consignment.objects.filter(reservation__request=need).update(dispatched_at=when + td(days=3))
        ReceiptEvent.objects.filter(consignment__reservation__request=need).update(created_at=when + td(days=4))
        Notification.objects.filter(created_at__gte=since).update(
            read_at=timezone.now(), created_at=when + td(days=4))

    def _history(self, rng):
        """About six months of completed reuse between departments, growing month on month."""
        from catalogue.models import Listing, ListingState
        from catalogue.services import CatalogueQueryService
        from sustainability.models import AvoidedPurchase, CostEntry

        who = [("sara.requester", "CHEM"), ("ali.mahmoud", "MECH"), ("dana.yousef", "FAC")]
        plan = [5, 4, 3, 2, 1, 0]  # months ago -> repeat counts below
        per_month = {5: 1, 4: 2, 3: 2, 2: 3, 1: 3, 0: 2}
        today = timezone.localdate()
        made = 0
        for months_ago in plan:
            for _ in range(per_month[months_ago]):
                requester, dept = who[made % 3]
                listings = [l for l in CatalogueQueryService.search(self.u[requester], {"availability": "available", "sort": "free"})
                            if l.department_id != self.d[dept].pk and l.free_qty >= 1
                            and not l.title.startswith(("Dell 24", "Olympus", "Benchtop", "Epson WXGA", "Mobile double",
                                                        "A4 copier", "Electric sit", "Cordless drill sets"))]
                if not listings:
                    continue
                listing = listings[made * 7 % len(listings)]
                qty = int(min(listing.free_qty, rng.choice([1, 2, 2, 3, 4])))
                since = timezone.now()
                need, res, cons = self._flow(requester, dept, listing, qty, f"{listing.title} for {self.d[dept].name}",
                                             "Reuse instead of a new purchase.", receive=qty)
                day = min(today.day, 20) if months_ago == 0 else rng.randint(3, 26)
                y, m = today.year, today.month - months_ago
                while m <= 0:
                    y, m = y - 1, m + 12
                when = timezone.make_aware(datetime(y, m, max(1, day - 5), 10, 0))
                self._backdate(need, when, since)
                value = listing.asset.estimated_value_aed or Decimal("600")
                if made % 2 == 0:
                    ap = AvoidedPurchase.objects.create(asset=listing.asset, quantity=qty, baseline_value_aed=value * qty,
                                                        procurement_reference=f"SYN-PR-HIST-{made:03d}",
                                                        is_procurement_validated=True, validated_at=when)
                    AvoidedPurchase.objects.filter(pk=ap.pk).update(recorded_at=when)
                ce = CostEntry.objects.create(asset=listing.asset, cost_type=CostEntry.CostType.TRANSFER,
                                              amount_aed=Decimal(rng.choice([120, 180, 240, 300])),
                                              description="Internal move (synthetic)", evidence_reference=f"SYN-MOVE-{made:03d}",
                                              recorded_by=self.u["reem.sustain"])
                CostEntry.objects.filter(pk=ce.pk).update(recorded_at=when)
                made += 1
        return made

    @transaction.atomic
    def _stage(self):
        import random

        from care.services import CareService
        from final_actions.services import FinalActionService
        from inventory.models import Lifecycle
        from sustainability.models import (CohortOutcome, CostEntry, EmissionFactor, LifeExtensionEvidence,
                                           UnwantedCohort)

        rng = random.Random(2026)
        today = timezone.localdate()

        # History first, so live scenarios start from a realistic six-month record.
        history = self._history(rng)

        # Partial delivery: 6 monitors sent to Sara, 4 confirmed, 2 still to confirm.
        monitors = self._asset("mariam.custodian", "MECH", "IT", "MC-A-STORE", "Dell 24-inch monitors P2422H",
                               "Full HD IPS monitors with height-adjustable stands and cables.", 10, value=780,
                               specs={"screen_in": "24"})
        monitors_l = self._listing(monitors, "mariam.custodian", release_by="khalid.rep")
        self._flow("sara.requester", "CHEM", monitors_l, 6, "Second screens for instrument PCs",
                   "Dual-screen setup for six instrument control PCs in C-210.", receive=4)

        # Approved transfer waiting for Mariam to dispatch.
        boards = self._asset("mariam.custodian", "FAC", "OFF", "MC-H-OFF", "Mobile double-sided whiteboards",
                             "Whiteboards on lockable wheels, 180 x 90 cm.", 5, value=900)
        boards_l = self._listing(boards, "mariam.custodian", release_by="khalid.rep")
        n3 = self._need("sara.requester", "CHEM", "Whiteboards for the teaching lab", "Two boards for group work in C-210.", 2, boards_l)
        self._approve_need("khalid.rep", n3)
        r3 = self._reserve("sara.requester", n3, boards_l, 2)
        self._hold("khalid.rep", r3)
        self._commit("khalid.rep", r3)

        # Held, waiting for Khalid to approve the transfer.
        scopes = self._asset("mariam.custodian", "MECH", "LAB", "MC-A-101", "Olympus CX23 teaching microscopes",
                             "Binocular microscopes with 4 objectives, calibrated 2026.", 6, value=4800,
                             specs={"model": "CX23", "power_w": 20, "calibrated": True})
        scopes_l = self._listing(scopes, "mariam.custodian", release_by="khalid.rep")
        n4 = self._need("sara.requester", "CHEM", "Microscopes for the first-year teaching lab",
                        "Two extra microscopes for the spring practical sessions.", 2, scopes_l,
                        urgent=True, reason="Practical sessions start in two weeks.")
        self._approve_need("khalid.rep", n4)
        r4 = self._reserve("sara.requester", n4, scopes_l, 2)
        self._hold("khalid.rep", r4)

        # Reservation waiting for Khalid's hold decision.
        centrifuge = self._asset("mariam.custodian", "MECH", "LAB", "MC-A-101", "Benchtop centrifuges EBA 200",
                                 "Variable speed, 6 x 50 ml rotor, serviced last year.", 2, value=2400,
                                 specs={"model": "EBA 200", "power_w": 250})
        centrifuge_l = self._listing(centrifuge, "mariam.custodian", release_by="khalid.rep")
        n5 = self._need("sara.requester", "CHEM", "Centrifuge for sample preparation", "One centrifuge for the sample prep bench.", 1, centrifuge_l)
        self._approve_need("khalid.rep", n5)
        self._reserve("sara.requester", n5, centrifuge_l, 1)

        # Needs waiting for Khalid's decision.
        projector = self._asset("mariam.custodian", "MECH", "AV", "MC-A-STORE", "Epson WXGA classroom projectors",
                                "3,600 lumen projectors with ceiling mount kits.", 3, value=2400,
                                specs={"resolution": "1280x800", "lumens": 3600})
        projector_l = self._listing(projector, "mariam.custodian", release_by="khalid.rep")
        self._need("sara.requester", "CHEM", "Projector for the seminar room", "Replace the failed projector in seminar room C-105.", 1, projector_l)
        paper = self._asset("mariam.custodian", "FAC", "OFF", "SAN-W1", "A4 copier paper, sealed boxes",
                            "Boxes of 5 reams, surplus from the 2026 order.", 20, value=150, specs={"pack_size": 5})
        paper_l = self._listing(paper, "mariam.custodian", release_by="khalid.rep")
        self._need("ali.mahmoud", "MECH", "Paper for the exam period", "Printing for mid-term exam papers.", 4, paper_l)

        # Listings in the release process.
        drills = self._asset("mariam.custodian", "MECH", "TOOL", "MC-A-STORE", "Cordless drill sets 18 V",
                             "Drill, two batteries and case. Workshop surplus.", 4, value=420,
                             specs={"power_w": 400, "cordless": True})
        self._listing(drills, "mariam.custodian")
        drills.refresh_from_db()
        # The release request must come from someone other than the reviewer.
        desks = self._asset("mariam.custodian", "MECH", "FURN", "MC-A-STORE", "Electric sit-stand desks",
                            "Height-adjustable desks, 160 x 80 cm, with cable trays.", 3, value=2400,
                            specs={"width_cm": "160", "depth_cm": "80", "adjustable": True})
        self._listing(desks, "mariam.custodian", release_by="khalid.rep", publish=False)
        self._asset("mariam.custodian", "MECH", "IT", "MC-A-101", "Lenovo ThinkPad T14 laptops",
                    "Teaching-lab laptops, batteries tested in October.", 5, value=2400,
                    specs={"ram_gb": 16, "storage_gb": 512, "cpu": "Ryzen 5 PRO"})

        # Care: a defect for Rashid, spend for Khalid, a repair for Rashid to verify, and history.
        hotplate = self._asset("mariam.custodian", "MECH", "LAB", "MC-A-101", "Magnetic stirrer hotplate",
                               "Ceramic top, up to 340 C.", 1, value=900, state="IN_USE")
        CareService.report_defect(self.u["mariam.custodian"], self._portion(hotplate).pk,
                                  "Temperature overshoots the set point by about 40 C.")
        balance2 = self._asset("mariam.custodian", "MECH", "LAB", "MC-A-101", "Analytical balance AX224, bench 2",
                               "0.1 mg balance with draft shield.", 1, value=4800, state="IN_USE")
        d = CareService.report_defect(self.u["mariam.custodian"], self._portion(balance2).pk, "Reading drifts after warm-up.")
        case = CareService.inspect(self.u["rashid.maint"], d.pk, "Load cell drift confirmed against a 100 g reference.")
        CareService.request_work(self.u["rashid.maint"], case.pk, case.version, "Recalibrate and replace the levelling feet. Estimate AED 300.")

        printer = self._asset("mariam.custodian", "CHEM", "AV", "MC-C-210", "Document camera, lecture room C-012",
                              "USB document camera on a flexible arm.", 1, value=900, state="IN_USE")
        sheet0 = self._evidence(printer, "mariam.custodian", "service-sheet-camera.pdf", "Synthetic service sheet")
        d = CareService.report_defect(self.u["mariam.custodian"], self._portion(printer).pk, "Image freezes after a few minutes.")
        case = CareService.inspect(self.u["lina.haddad"], d.pk, "USB cable damaged; firmware outdated.")
        case = CareService.request_work(self.u["lina.haddad"], case.pk, case.version, "Replace cable and update firmware.")
        case = CareService.approve_work(self.u["khalid.rep"], case.pk, case.version)
        CareService.finish_work(self.u["lina.haddad"], case.pk, case.version, "Cable replaced, firmware 2.4 installed.")

        repairs = [("Epson projector, lecture room A-012", "AV", True, 480), ("Analytical balance AX224, bench 4", "LAB", False, 260),
                   ("Ergonomic chair, office H-14", "FURN", True, 90), ("Dell Latitude 7420 laptop, A-101", "IT", True, 210)]
        for i, (title, cat, ok, cost) in enumerate(repairs):
            a = self._asset("mariam.custodian", "MECH", cat, "MC-A-101", title, "In active use.", 1, value=2400, state="IN_USE")
            ev = self._evidence(a, "mariam.custodian", f"service-{i}.pdf", "Synthetic service report")
            d = CareService.report_defect(self.u["mariam.custodian"], self._portion(a).pk, "Intermittent fault reported by staff.")
            c = CareService.inspect(self.u["rashid.maint"], d.pk, "Fault reproduced.")
            c = CareService.request_work(self.u["rashid.maint"], c.pk, c.version, "Replace the faulty part.")
            c = CareService.approve_work(self.u["khalid.rep"], c.pk, c.version)
            c = CareService.finish_work(self.u["rashid.maint"], c.pk, c.version, "Part replaced.")
            CareService.verify(self.u["lina.haddad"], c.pk, c.version, ok, ev.pk)
            CostEntry.objects.create(asset=a, cost_type=CostEntry.CostType.REPAIR, amount_aed=Decimal(cost),
                                     description="Repair parts (synthetic)", evidence_reference=f"SYN-WO-{i}",
                                     recorded_by=self.u["reem.sustain"])
            if ok:
                LifeExtensionEvidence.objects.create(asset=a, baseline_retirement_date=today - timedelta(days=30),
                                                     revised_retirement_date=today + timedelta(days=540 + 90 * i),
                                                     verified_continued_use=True, verification_date=today,
                                                     evidence_reference=f"care:{c.pk}")

        # Final actions: a completed donation and a recycling proposal for Khalid.
        binders = self._asset("mariam.custodian", "FAC", "OFF", "SAN-W1", "Lever arch binders, unused",
                              "Blue A4 binders from a cancelled programme.", 10, value=150)
        receipt = self._evidence(binders, "mariam.custodian", "donation-receipt.pdf", "Synthetic recipient receipt")
        cohort = UnwantedCohort.objects.create(asset=binders, portion=self._portion(binders), quantity=10,
                                               evidence_reference="SYN-SURPLUS-FAC-07", recorded_by=self.u["mariam.custodian"])
        fa = FinalActionService.propose(self.u["mariam.custodian"], self._portion(binders).pk, 10, Lifecycle.DONATED,
                                        "No internal demand after 60 days on the exchange.", "Al Ain community school")
        fa = FinalActionService.approve(self.u["khalid.rep"], fa.pk, fa.version)
        FinalActionService.execute(self.u["mariam.custodian"], fa.pk, Decimal(10), receipt.pk, self._key())
        CohortOutcome.objects.create(cohort=cohort, outcome=CohortOutcome.Outcome.DONATION, quantity=10,
                                     evidence_reference=f"final:{fa.pk}", recorded_by=self.u["mariam.custodian"])
        old_monitors = self._asset("mariam.custodian", "CHEM", "IT", "MC-C-STORE", "CRT-era monitors, unrepairable",
                                   "Faulty 19-inch monitors, data-free.", 6, condition="POOR")
        cohort2 = UnwantedCohort.objects.create(asset=old_monitors, portion=self._portion(old_monitors), quantity=6,
                                                evidence_reference="SYN-SURPLUS-CHEM-03", recorded_by=self.u["mariam.custodian"])
        CohortOutcome.objects.create(cohort=cohort2, outcome=CohortOutcome.Outcome.RECYCLING, quantity=4,
                                     evidence_reference="SYN-RECYCLE-CERT-118", recorded_by=self.u["mariam.custodian"])
        chairs_old = self._asset("mariam.custodian", "FAC", "FURN", "MC-H-OFF", "Visitor chairs from the old reception",
                                 "Upholstered visitor chairs, replaced in the lobby refit.", 8, condition="FAIR", value=350)
        cohort3 = UnwantedCohort.objects.create(asset=chairs_old, portion=self._portion(chairs_old), quantity=8,
                                                evidence_reference="SYN-SURPLUS-FAC-11", recorded_by=self.u["mariam.custodian"])
        CohortOutcome.objects.create(cohort=cohort3, outcome=CohortOutcome.Outcome.REUSE, quantity=6,
                                     evidence_reference="SYN-REUSE-FAC-11", recorded_by=self.u["mariam.custodian"])
        stack = self._asset("mariam.custodian", "MECH", "FURN", "MC-A-STORE", "Cracked stacking chairs",
                            "Polypropylene shells cracked; frames reusable as scrap steel.", 3, condition="POOR", value=None)
        UnwantedCohort.objects.create(asset=stack, portion=self._portion(stack), quantity=3,
                                      evidence_reference="SYN-SURPLUS-MECH-12", recorded_by=self.u["mariam.custodian"])
        FinalActionService.propose(self.u["mariam.custodian"], self._portion(stack).pk, 3, Lifecycle.RECYCLED,
                                   "Shells cannot be repaired; send frames for metal recycling.")

        for activity, name, kg, unit in [
            ("replacement:FURN", "New office chair, cradle-to-gate", "72.0", "unit"),
            ("replacement:IT", "New 24-inch monitor, cradle-to-gate", "300.0", "unit"),
            ("replacement:LAB", "New teaching microscope, cradle-to-gate", "180.0", "unit"),
            ("replacement:AV", "New classroom AV device, cradle-to-gate", "150.0", "unit"),
            ("replacement:OFF", "New office supplies, per pack", "8.0", "unit"),
            ("replacement:TOOL", "New workshop tool, cradle-to-gate", "40.0", "unit"),
            ("reuse:transfer", "Internal campus move by van", "2.5", "unit moved"),
        ]:
            EmissionFactor.objects.get_or_create(activity=activity, defaults={
                "name": name, "kg_co2e_per_unit": Decimal(kg), "unit": unit, "version": "demo-1",
                "source_reference": "Synthetic demo factor (not a published source)", "valid_from": date(2026, 1, 1)})
        self.stdout.write(f"  {history} completed history transfers, plus live scenarios for every role")
