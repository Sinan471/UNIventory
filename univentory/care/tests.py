from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from core.contracts import NotPermitted
from core.testing import World, actor, batch, user
from identity.models import Role
from inventory.models import AttachmentAccess, Lifecycle, SafetyState
from inventory.services import AttachmentService
from .services import CareService


class DefectTests(TestCase):
    def test_defect_restricts_stock_and_denies_other_users(self):
        world = World()
        asset = batch(world.custodian, world.dept, world.loc, world.cat)
        portion = asset.portions.get(is_active_leaf=True)
        with self.assertRaises(NotPermitted):
            CareService.report_defect(world.requester, portion.pk, "Loose part")
        CareService.report_defect(world.custodian, portion.pk, "Loose part")
        portion.refresh_from_db()
        self.assertEqual(portion.safety_state, SafetyState.RESTRICTED)

    def test_work_needs_independent_approval_and_verification(self):
        world = World()
        technician = user("technician", (Role.MAINTENANCE, world.dept))
        verifier = user("verifier", (Role.MAINTENANCE, world.dept))
        asset = batch(world.custodian, world.dept, world.loc, world.cat)
        report = CareService.report_defect(world.custodian, asset.portions.get(is_active_leaf=True).pk, "Loose part")
        case = CareService.inspect(technician, report.pk, "Part is loose")
        case = CareService.request_work(technician, case.pk, case.version, "Replace fitting")
        with self.assertRaises(NotPermitted):
            CareService.approve_work(technician, case.pk, case.version)
        case = CareService.approve_work(world.rep, case.pk, case.version)
        case = CareService.finish_work(technician, case.pk, case.version, "Fitting replaced")
        evidence = AttachmentService.store(actor(world.custodian), asset, SimpleUploadedFile("verification.pdf", b"%PDF-1.4\nverified\n%%EOF"), access_class=AttachmentAccess.RESTRICTED)
        with self.assertRaises(NotPermitted):
            CareService.verify(technician, case.pk, case.version, True, evidence.pk)
        case = CareService.verify(verifier, case.pk, case.version, True, evidence.pk)
        case.portion.refresh_from_db()
        self.assertEqual(case.portion.safety_state, SafetyState.CLEARED)
        self.assertEqual(case.portion.lifecycle_state, Lifecycle.IN_USE)

    def test_failed_work_stays_restricted_and_rework_is_linked(self):
        world = World()
        technician = user("tech2", (Role.MAINTENANCE, world.dept))
        verifier = user("verifier2", (Role.MAINTENANCE, world.dept))
        asset = batch(world.custodian, world.dept, world.loc, world.cat)
        report = CareService.report_defect(world.custodian, asset.portions.get(is_active_leaf=True).pk, "Fault")
        case = CareService.inspect(technician, report.pk, "Inspect")
        case = CareService.request_work(technician, case.pk, case.version, "Repair")
        case = CareService.approve_work(world.rep, case.pk, case.version)
        case = CareService.finish_work(technician, case.pk, case.version, "Attempted")
        evidence = AttachmentService.store(actor(world.custodian), asset, SimpleUploadedFile("report.pdf", b"%PDF-1.4\nfailed\n%%EOF"), access_class=AttachmentAccess.RESTRICTED)
        case = CareService.verify(verifier, case.pk, case.version, False, evidence.pk)
        self.assertEqual(case.portion.safety_state, SafetyState.RESTRICTED)
        self.assertEqual(case.portion.lifecycle_state, Lifecycle.UNDER_INSPECTION)
        rework = CareService.inspect(technician, report.pk, "Inspect again", previous_case_id=case.pk)
        self.assertEqual(rework.previous_case_id, case.pk)
