from django.db import transaction
from core.contracts import ActorContext, NotPermitted, StaleVersion, ValidationFailed
from core.contracts.audit import audit
from identity.policy import AccessPolicy
from identity.models import Role
from inventory.ledger import InventoryLedger
from inventory.models import AssetPortion, Attachment, Lifecycle, SafetyState
from .models import DefectReport, MaintenanceCase


class CareService:
    @staticmethod
    @transaction.atomic
    def report_defect(user, portion_id, description):
        portion = AssetPortion.objects.select_for_update().select_related("asset").get(pk=portion_id)
        if not AccessPolicy.can_edit_asset(user, portion.asset):
            raise NotPermitted("Only the assigned asset custodian can report a defect here.")
        if not description.strip():
            raise ValidationFailed("Describe the defect.")
        report = DefectReport.objects.create(asset=portion.asset, portion=portion, reported_by=user, description=description.strip())
        actor = ActorContext(user, operation_key=f"defect:{report.pk}")
        InventoryLedger.record_safety(actor, portion.pk, SafetyState.RESTRICTED, evidence_ref=f"defect:{report.pk}")
        audit("care.defect_reported", report, actor, after={"asset": portion.asset_id, "safety": SafetyState.RESTRICTED})
        return report

    @staticmethod
    @transaction.atomic
    def inspect(user, defect_id, notes, previous_case_id=None):
        defect = DefectReport.objects.select_for_update().select_related("asset", "portion").get(pk=defect_id)
        if not AccessPolicy.has_role(user, Role.MAINTENANCE, defect.portion.department_id):
            raise NotPermitted("A maintenance specialist must perform the inspection.")
        if not notes.strip():
            raise ValidationFailed("Record the inspection findings.")
        if MaintenanceCase.objects.filter(defect=defect).exclude(state=MaintenanceCase.State.CLOSED).exists():
            raise ValidationFailed("This defect already has an open maintenance case.")
        previous = None
        if previous_case_id:
            previous = MaintenanceCase.objects.filter(pk=previous_case_id, defect=defect, state=MaintenanceCase.State.CLOSED, outcome="FAILED").first()
            if previous is None:
                raise ValidationFailed("Rework must refer to a failed closed case for this defect.")
        current_portion = previous.portion if previous else defect.portion
        row = MaintenanceCase.objects.create(defect=defect, portion=current_portion, opened_by=user, inspection_notes=notes.strip(), previous_case=previous)
        actor = ActorContext(user, operation_key=f"inspection:{row.pk}")
        part = current_portion
        if part.lifecycle_state != Lifecycle.UNDER_INSPECTION:
            part = InventoryLedger.change_lifecycle(actor, part.pk, Lifecycle.UNDER_INSPECTION, reference=f"care:{row.pk}")
            row.portion = part
            row.save(update_fields=["portion"])
        audit("care.inspection", row, actor, after={"state": row.state})
        return row

    @staticmethod
    @transaction.atomic
    def no_repair_needed(user, case_id, expected_version, evidence_id):
        row = MaintenanceCase.objects.select_for_update().select_related("portion", "defect__asset").get(pk=case_id)
        if not AccessPolicy.has_role(user, Role.MAINTENANCE, row.portion.department_id) or user.pk == row.opened_by_id:
            raise NotPermitted("An independent maintenance specialist must verify the inspection.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != MaintenanceCase.State.INSPECTION:
            raise ValidationFailed("This inspection is no longer open.")
        evidence = Attachment.objects.filter(pk=evidence_id, asset=row.defect.asset, status="ACCEPTED", withdrawn_at__isnull=True).first()
        if evidence is None:
            raise ValidationFailed("An accepted verification attachment is required.")
        actor = ActorContext(user, operation_key=f"care-no-repair:{row.pk}:{row.version}")
        InventoryLedger.record_safety(actor, row.portion_id, SafetyState.CLEARED, evidence_ref=f"attachment:{evidence.pk}")
        part = InventoryLedger.change_lifecycle(ActorContext(user, operation_key=f"care-no-repair-return:{row.pk}:{row.version}"), row.portion_id, Lifecycle.IN_USE, reference=f"care:{row.pk}")
        row.portion, row.verified_by, row.evidence = part, user, evidence
        row.outcome, row.state, row.version = "NO_REPAIR", MaintenanceCase.State.CLOSED, row.version + 1
        row.save(update_fields=["portion", "verified_by", "evidence", "outcome", "state", "version"])
        audit("care.no_repair_needed", row, actor, after={"outcome": row.outcome})
        return row

    @staticmethod
    @transaction.atomic
    def request_work(user, case_id, expected_version, notes):
        row = MaintenanceCase.objects.select_for_update().select_related("portion").get(pk=case_id)
        if not AccessPolicy.has_role(user, Role.MAINTENANCE, row.portion.department_id):
            raise NotPermitted("A maintenance specialist must propose work.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != MaintenanceCase.State.INSPECTION or not notes.strip():
            raise ValidationFailed("Add a work plan to an open inspection.")
        row.technician, row.work_notes, row.state, row.version = user, notes.strip(), MaintenanceCase.State.AWAITING_APPROVAL, row.version + 1
        row.save(update_fields=["technician", "work_notes", "state", "version"])
        audit("care.work_requested", row, user, after={"state": row.state})
        return row

    @staticmethod
    @transaction.atomic
    def approve_work(user, case_id, expected_version):
        row = MaintenanceCase.objects.select_for_update().select_related("portion").get(pk=case_id)
        if not AccessPolicy.has_role(user, Role.DEPT_REP, row.portion.department_id) or user.pk in (row.opened_by_id, row.technician_id):
            raise NotPermitted("An independent department representative must approve work.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != MaintenanceCase.State.AWAITING_APPROVAL:
            raise ValidationFailed("This work is not awaiting approval.")
        actor = ActorContext(user, operation_key=f"care-work:{row.pk}:{row.version}")
        row.portion = InventoryLedger.change_lifecycle(actor, row.portion_id, Lifecycle.UNDER_MAINTENANCE, reference=f"care:{row.pk}")
        row.approved_by, row.state, row.version = user, MaintenanceCase.State.IN_PROGRESS, row.version + 1
        row.save(update_fields=["portion", "approved_by", "state", "version"])
        audit("care.work_approved", row, actor, after={"state": row.state})
        return row

    @staticmethod
    @transaction.atomic
    def finish_work(user, case_id, expected_version, notes):
        row = MaintenanceCase.objects.select_for_update().select_related("portion").get(pk=case_id)
        if user.pk != row.technician_id or not AccessPolicy.has_role(user, Role.MAINTENANCE, row.portion.department_id):
            raise NotPermitted("Only the assigned maintenance specialist can finish this work.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != MaintenanceCase.State.IN_PROGRESS or not notes.strip():
            raise ValidationFailed("Record the work performed.")
        row.work_notes += "\nCompleted: " + notes.strip()
        row.state, row.version = MaintenanceCase.State.VERIFY, row.version + 1
        row.save(update_fields=["work_notes", "state", "version"])
        audit("care.work_completed", row, user, after={"state": row.state})
        return row

    @staticmethod
    @transaction.atomic
    def verify(user, case_id, expected_version, success, evidence_id):
        row = MaintenanceCase.objects.select_for_update().select_related("portion", "defect__asset").get(pk=case_id)
        if not AccessPolicy.has_role(user, Role.MAINTENANCE, row.portion.department_id) or user.pk == row.technician_id:
            raise NotPermitted("An independent maintenance specialist must verify the work.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != MaintenanceCase.State.VERIFY:
            raise ValidationFailed("This work is not awaiting verification.")
        evidence = Attachment.objects.filter(pk=evidence_id, asset=row.defect.asset, status="ACCEPTED", withdrawn_at__isnull=True).first()
        if evidence is None:
            raise ValidationFailed("An accepted verification attachment is required.")
        actor = ActorContext(user, operation_key=f"care-verify:{row.pk}:{row.version}")
        if success:
            InventoryLedger.record_safety(actor, row.portion_id, SafetyState.CLEARED, evidence_ref=f"attachment:{evidence.pk}")
            part = InventoryLedger.change_lifecycle(ActorContext(user, operation_key=f"care-return:{row.pk}:{row.version}"), row.portion_id, Lifecycle.IN_USE, reference=f"care:{row.pk}")
        else:
            part = InventoryLedger.change_lifecycle(actor, row.portion_id, Lifecycle.UNDER_INSPECTION, reference=f"care:{row.pk}")
        row.portion, row.verified_by, row.evidence = part, user, evidence
        row.outcome, row.state, row.version = "SUCCESS" if success else "FAILED", MaintenanceCase.State.CLOSED, row.version + 1
        row.save(update_fields=["portion", "verified_by", "evidence", "outcome", "state", "version"])
        audit("care.verification", row, actor, after={"outcome": row.outcome})
        return row
