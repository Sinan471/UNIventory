"""Seed labelled synthetic development data (plan Section 17).

Creates three departments, six categories, development accounts for each
role and N synthetic assets (default 120; use --assets 1000 for the load
set). Every asset is marked provenance=SYNTHETIC. Safety clearances use the
evidence reference "synthetic-seed-clearance" so they are never mistaken
for a real inspection. Development accounts use the dev-test issuer and can
only sign in through the DEBUG-only test adapter.
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalogue.models import ListingState
from catalogue.services import CatalogueService
from core.contracts import ActorContext, get_adapter
from core.contracts.approvals import ReleaseStatus
from identity.models import AppUser, Category, Department, Location, Role, UserRole
from inventory.ledger import InventoryLedger
from inventory.models import AssetPortion, Condition, Lifecycle, SafetyState, TrackingType, Unit
from inventory.services import AssetInput, InventoryService

DEPARTMENTS = [
    ("MECH", "Mechanical Engineering", "الهندسة الميكانيكية"),
    ("CHEM", "Chemistry", "الكيمياء"),
    ("FAC", "Facilities and Administration", "المرافق والإدارة"),
]
LOCATIONS = [
    ("MC-A-101", "Lab A-101", "Building A", "Main Campus", "MECH"),
    ("MC-A-STORE", "A-Wing Store", "Building A", "Main Campus", "MECH"),
    ("MC-C-210", "Chem Lab C-210", "Building C", "Main Campus", "CHEM"),
    ("MC-C-STORE", "C-Wing Store", "Building C", "Main Campus", "CHEM"),
    ("SAN-W1", "SAN Warehouse 1", "Warehouse", "SAN Campus", "FAC"),
    ("MC-H-OFF", "Admin Offices H", "Building H", "Main Campus", "FAC"),
]
CATEGORIES = [
    ("IT", "IT Equipment", "معدات تقنية المعلومات", "it", ["Laptop", "Desktop", "Monitor", "Printer"],
     [{"key": "ram_gb", "label": "RAM", "type": "integer", "unit": "GB"},
      {"key": "storage_gb", "label": "Storage", "type": "integer", "unit": "GB"},
      {"key": "cpu", "label": "Processor", "type": "text"},
      {"key": "screen_in", "label": "Screen size", "type": "decimal", "unit": "in"}]),
    ("FURN", "Furniture", "الأثاث", "furniture", ["Chair", "Desk", "Cabinet", "Table"],
     [{"key": "width_cm", "label": "Width", "type": "decimal", "unit": "cm"},
      {"key": "depth_cm", "label": "Depth", "type": "decimal", "unit": "cm"},
      {"key": "height_cm", "label": "Height", "type": "decimal", "unit": "cm"},
      {"key": "adjustable", "label": "Adjustable", "type": "boolean"}]),
    ("LAB", "Laboratory Equipment", "معدات المختبرات", "lab", ["Microscope", "Centrifuge", "Balance", "Hotplate"],
     [{"key": "model", "label": "Model", "type": "text"},
      {"key": "power_w", "label": "Power rating", "type": "integer", "unit": "W"},
      {"key": "calibrated", "label": "Calibration current", "type": "boolean"}]),
    ("AV", "Audio-Visual", "السمعية والبصرية", "av", ["Projector", "Display", "Speaker", "Camera"],
     [{"key": "resolution", "label": "Resolution", "type": "text"},
      {"key": "lumens", "label": "Brightness", "type": "integer", "unit": "lm"}]),
    ("OFF", "Office Supplies", "اللوازم المكتبية", "office", ["Paper", "Binders", "Whiteboard", "Stationery"],
     [{"key": "pack_size", "label": "Pack size", "type": "integer", "unit": "items"}]),
    ("TOOL", "Tools and Workshop", "الأدوات والورشة", "tools", ["Hand tool", "Power tool", "Workbench", "Safety kit"],
     [{"key": "power_w", "label": "Power rating", "type": "integer", "unit": "W"},
      {"key": "cordless", "label": "Cordless", "type": "boolean"}]),
]
ITEMS = {
    "IT": [("Dell Latitude 7420 laptop", "14-inch business laptop with charger.", {"ram_gb": 16, "storage_gb": 512, "cpu": "Intel i7-1185G7", "screen_in": "14"}),
           ("HP EliteDesk 800 G6", "Small form factor desktop, keyboard and mouse included.", {"ram_gb": 16, "storage_gb": 256, "cpu": "Intel i5-10500"}),
           ("Dell 27-inch monitor P2722H", "Full HD IPS monitor with height-adjustable stand.", {"screen_in": "27"}),
           ("Lenovo ThinkPad T14", "Laptop for teaching labs, battery health good.", {"ram_gb": 8, "storage_gb": 256, "cpu": "Ryzen 5 PRO"})],
    "FURN": [("Ergonomic office chair", "Mesh back, adjustable arms and lumbar support.", {"adjustable": True, "height_cm": "110"}),
             ("Stacking seminar chairs", "Polypropylene stacking chairs, grey.", {"width_cm": "52", "depth_cm": "54", "height_cm": "80"}),
             ("Height-adjustable desk", "Electric sit-stand desk, 160 x 80 cm.", {"width_cm": "160", "depth_cm": "80", "adjustable": True}),
             ("Steel filing cabinet", "Four-drawer lockable cabinet with keys.", {"width_cm": "47", "depth_cm": "62", "height_cm": "132"})],
    "LAB": [("Olympus CX23 microscope", "Binocular teaching microscope with 4 objectives.", {"model": "CX23", "power_w": 20, "calibrated": True}),
            ("Benchtop centrifuge", "Variable speed centrifuge, 6 x 50 ml rotor.", {"model": "EBA 200", "power_w": 250}),
            ("Analytical balance 0.1 mg", "Internal calibration, draft shield.", {"model": "AX224", "calibrated": False}),
            ("Magnetic stirrer hotplate", "Ceramic top, up to 340 C.", {"power_w": 630})],
    "AV": [("Epson classroom projector", "WXGA projector with ceiling mount kit.", {"resolution": "1280x800", "lumens": 3600}),
           ("65-inch interactive display", "Touch display on mobile stand.", {"resolution": "3840x2160"}),
           ("Conference speakerphone", "USB speakerphone for small rooms.", {}),
           ("Document camera", "USB document camera for lectures.", {"resolution": "1920x1080"})],
    "OFF": [("A4 copier paper boxes", "Sealed boxes of 5 reams.", {"pack_size": 5}),
            ("Lever arch binders", "Blue A4 binders, unused.", {"pack_size": 10}),
            ("Mobile whiteboard", "Double-sided whiteboard on wheels.", {}),
            ("Desk organiser sets", "Stationery organisers, unused stock.", {"pack_size": 4})],
    "TOOL": [("Cordless drill set", "18 V drill with two batteries and case.", {"power_w": 400, "cordless": True}),
             ("Workshop workbench", "Steel frame workbench with vice.", {}),
             ("Digital caliper set", "150 mm digital calipers.", {}),
             ("Safety goggles box", "Box of anti-fog safety goggles.", {})],
}
USERS = [
    # username, display name, [(role, dept code or None)]
    ("admin", "Hessa Al Mansoori (System Admin)", [("SYSADMIN", None)]),
    ("mariam.custodian", "Mariam Al Hammadi (Custodian, MECH)", [("CUSTODIAN", "MECH")]),
    ("omar.custodian", "Omar Haddad (Custodian, CHEM)", [("CUSTODIAN", "CHEM")]),
    ("fatima.custodian", "Fatima Rahman (Custodian, FAC)", [("CUSTODIAN", "FAC")]),
    ("khalid.rep", "Khalid Al Suwaidi (Dept Rep, MECH)", [("DEPT_REP", "MECH")]),
    ("aisha.rep", "Aisha Noor (Dept Rep, CHEM)", [("DEPT_REP", "CHEM")]),
    ("yousef.rep", "Yousef Karim (Dept Rep, FAC)", [("DEPT_REP", "FAC")]),
    ("sara.requester", "Sara Ibrahim (Requester, CHEM)", [("REQUESTER", "CHEM")]),
    ("ali.requester", "Ali Mahmoud (Requester, MECH)", [("REQUESTER", "MECH")]),
    ("noura.campus", "Noura Saeed (Campus User)", [("CAMPUS_USER", None)]),
    ("tariq.norole", "Tariq Aziz (no role yet)", []),
]


class Command(BaseCommand):
    help = "Seed labelled synthetic data for development and demonstration."

    def add_arguments(self, parser):
        parser.add_argument("--assets", type=int, default=120)
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, **options):
        rng = random.Random(options["seed"])
        with transaction.atomic():
            depts = self._reference()
            users = self._users(depts)
        custodians = {"MECH": users["mariam.custodian"], "CHEM": users["omar.custodian"],
                      "FAC": users["fatima.custodian"]}
        reps = {"MECH": users["khalid.rep"], "CHEM": users["aisha.rep"], "FAC": users["yousef.rep"]}
        existing = AppUser.objects.filter(pk__in=[u.pk for u in custodians.values()]).count()
        if existing != 3:
            raise CommandError("Custodian accounts missing.")
        created = published = 0
        categories = {c.code: c for c in Category.objects.all()}
        locations = list(Location.objects.select_related("department"))
        for index in range(options["assets"]):
            dept_code = DEPARTMENTS[index % 3][0]
            cat_code = CATEGORIES[index % 6][0]
            title, description, specs = rng.choice(ITEMS[cat_code])
            dept = depts[dept_code]
            location = rng.choice([loc for loc in locations if loc.department_id == dept.pk])
            batch = cat_code in {"FURN", "OFF", "TOOL"} and rng.random() < 0.6
            quantity = Decimal(rng.choice([4, 6, 10, 12, 20])) if batch else Decimal(1)
            acquired = timezone.localdate() - timedelta(days=rng.randint(60, 3000)) if rng.random() > 0.15 else None
            value = Decimal(rng.choice([150, 420, 900, 2400, 4800, 12500])) if rng.random() > 0.1 else None
            actor = ActorContext(user=custodians[dept_code])
            with transaction.atomic():
                asset = InventoryService.register(actor, AssetInput(
                    title=title, description=description, category=categories[cat_code], department=dept,
                    location=location, tracking_type=TrackingType.BATCH if batch else TrackingType.INDIVIDUAL,
                    quantity=quantity, unit=Unit.EACH,
                    condition=rng.choice([Condition.FAIR, Condition.GOOD, Condition.GOOD, Condition.EXCELLENT]),
                    tags=[cat_code.lower(), "seed"],
                    acquisition_date=acquired, acquisition_date_unknown=acquired is None,
                    estimated_value_aed=value, estimated_value_unknown=value is None, specifications=specs,
                    provenance="SYNTHETIC",
                ), activate_as=Lifecycle.AVAILABLE if rng.random() < 0.7 else Lifecycle.IN_USE)
                created += 1
                portion = asset.portions.filter(is_active_leaf=True).first()
                if portion.lifecycle_state == Lifecycle.AVAILABLE and rng.random() < 0.85:
                    InventoryLedger.record_safety(actor, portion.pk, SafetyState.CLEARED,
                                                  evidence_ref="synthetic-seed-clearance")
            if asset.portions.filter(safety_state=SafetyState.CLEARED).exists() and rng.random() < 0.75:
                published += self._publish(asset, actor, reps[dept_code])
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created} synthetic assets ({published} published listings), "
            f"{len(USERS)} development accounts. Sign in at /identity/sign-in/ with DEBUG on."
        ))

    # ------------------------------------------------------------------
    def _reference(self):
        depts = {}
        for code, name, name_ar in DEPARTMENTS:
            depts[code], _ = Department.objects.update_or_create(code=code, defaults={"name": name, "name_ar": name_ar})
        for code, name, building, campus, dept in LOCATIONS:
            Location.objects.update_or_create(code=code, defaults={
                "name": name, "building": building, "campus": campus, "site": campus, "department": depts[dept]})
        for code, name, name_ar, art, subs, schema in CATEGORIES:
            Category.objects.update_or_create(code=code, defaults={
                "name": name, "name_ar": name_ar, "illustration": art, "subcategories": subs, "spec_schema": schema})
        return depts

    def _users(self, depts):
        out = {}
        roles = {r.code: r for r in Role.objects.all()}
        for username, display, grants in USERS:
            user, created = AppUser.objects.get_or_create(
                username=username,
                defaults={"display_name": display, "email": f"{username}@example.invalid",
                          "identity_issuer": "dev-test", "identity_subject": f"dev-{username}"},
            )
            if created:
                user.set_unusable_password()
                user.save()
            for role_code, dept_code in grants:
                UserRole.objects.get_or_create(
                    user=user, role=roles[role_code], department=depts.get(dept_code) if dept_code else None,
                    revoked_at=None, defaults={"reason": "Synthetic seed grant"},
                )
            out[username] = user
        return out

    def _publish(self, asset, actor, rep) -> int:
        from catalogue.models import Listing

        if Listing.objects.filter(asset=asset, state__in=ListingState.open_states()).exists():
            return 0
        portion = AssetPortion.objects.filter(asset=asset, is_active_leaf=True).first()
        listing = CatalogueService.create(
            actor, asset=asset, title=asset.title, public_description=asset.description,
            offered_quantity=portion.quantity, collection_info=f"{portion.location.building}, {portion.location.name}. "
                                                              "Sun-Thu 08:00-15:00.",
        )
        listing = CatalogueService.transition(actor, listing.pk, "submit", expected_version=listing.version)
        get_adapter("RELEASE_APPROVALS").decide(listing=listing, decider=rep, status=ReleaseStatus.APPROVED)
        CatalogueService.transition(actor, listing.pk, "publish", expected_version=listing.version)
        return 1
