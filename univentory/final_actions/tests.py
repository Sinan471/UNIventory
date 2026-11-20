from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from core.contracts import NotPermitted, ValidationFailed
from core.testing import World, actor, batch
from inventory.models import AttachmentAccess, Lifecycle
from inventory.services import AttachmentService
from .models import FinalAction
from .services import FinalActionService


class FinalActionTests(TestCase):
    def test_independent_approval_and_evidence_for_execution(self):
        world = World()
        asset = batch(world.custodian, world.dept, world.loc, world.cat, quantity=3)
        portion = asset.portions.get(is_active_leaf=True)
        action = FinalActionService.propose(world.custodian, portion.pk, 2, Lifecycle.DONATED, "No longer needed", "Local charity")
        with self.assertRaises(NotPermitted):
            FinalActionService.approve(world.custodian, action.pk, 1)
        action = FinalActionService.approve(world.rep, action.pk, 1)
        with self.assertRaises(ValidationFailed):
            FinalActionService.execute(world.custodian, action.pk, 1, 999, "execution-key")
        attachment = AttachmentService.store(actor(world.custodian), asset, SimpleUploadedFile("receipt.pdf", b"%PDF-1.4\nreceipt\n%%EOF"), access_class=AttachmentAccess.RESTRICTED)
        first = FinalActionService.execute(world.custodian, action.pk, 1, attachment.pk, "execution-key")
        second = FinalActionService.execute(world.custodian, action.pk, 1, attachment.pk, "execution-key")
        self.assertEqual(first.pk, second.pk)
        action.refresh_from_db()
        self.assertEqual(action.state, FinalAction.State.IN_PROGRESS)

    def test_data_bearing_asset_cannot_bypass_clearance(self):
        world = World()
        asset = batch(world.custodian, world.dept, world.loc, world.cat, is_data_bearing=True, handling_notes="Requires data clearing")
        with self.assertRaises(ValidationFailed):
            FinalActionService.propose(world.custodian, asset.portions.get(is_active_leaf=True).pk, 1, Lifecycle.DISPOSED, "Obsolete")
