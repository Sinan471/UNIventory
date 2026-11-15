from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from core.contracts import ActorContext, NotPermitted, StaleVersion, ValidationFailed
from core.contracts.audit import audit
from identity.models import Role
from identity.policy import AccessPolicy
from inventory.ledger import InventoryLedger
from inventory.models import Allocation, AssetPortion, Attachment, Lifecycle
from .models import FinalAction, FinalActionExecution


class FinalActionService:
    # Recovery requires the separate linked-component workflow; do not allow
    # it here until that workflow exists. Restricted handling needs review.
    OUTCOMES = {Lifecycle.DONATED, Lifecycle.RECYCLED, Lifecycle.DISPOSED}

    @staticmethod
    def check_asset(asset):
        if asset.has_restriction and not asset.release_rights_confirmed:
            raise ValidationFailed("Resolve ownership or release restrictions first.")
        if asset.is_data_bearing or asset.is_hazardous or asset.is_regulated:
            raise ValidationFailed("A specialist clearance workflow is required for this asset before a final action.")

    @classmethod
    @transaction.atomic
    def propose(cls, user, portion_id, quantity, outcome, reason, recipient=""):
        portion = AssetPortion.objects.select_for_update().select_related("asset", "department").get(pk=portion_id)
        if not AccessPolicy.can_edit_asset(user, portion.asset):
            raise NotPermitted("Only the assigned custodian can propose this action.")
        cls.check_asset(portion.asset)
        qty = Decimal(str(quantity))
        if outcome not in cls.OUTCOMES or qty <= 0 or qty > portion.quantity or not portion.is_active_leaf or portion.allocation != Allocation.FREE:
            raise ValidationFailed("Choose an eligible outcome and available quantity.")
        if not reason.strip() or (outcome == Lifecycle.DONATED and not recipient.strip()):
            raise ValidationFailed("A reason and, for a donation, a recipient are required.")
        row = FinalAction.objects.create(asset=portion.asset, portion=portion, department=portion.department,
            proposed_by=user, quantity=qty, outcome=outcome, reason=reason.strip(), recipient=recipient.strip())
        audit("final.propose", row, user, after={"outcome": outcome, "quantity": str(qty)})
        return row

    @classmethod
    @transaction.atomic
    def approve(cls, user, action_id, expected_version):
        row = FinalAction.objects.select_for_update().select_related("asset", "portion").get(pk=action_id)
        if not AccessPolicy.has_role(user, Role.DEPT_REP, row.department_id) or user.pk == row.proposed_by_id:
            raise NotPermitted("An independent department representative must approve this action.")
        if row.version != expected_version:
            raise StaleVersion()
        if row.state != FinalAction.State.PROPOSED:
            raise ValidationFailed("This action is no longer awaiting approval.")
        cls.check_asset(row.asset)
        actor = ActorContext(user, operation_key=f"final-claim:{row.pk}:{row.version}")
        InventoryLedger.claim(actor, candidate_portion_ids=[row.portion_id], quantity=row.quantity,
                              claim_ref=row.claim_ref, allocation=Allocation.FINAL_COMMITTED)
        row.state, row.approved_by, row.version = FinalAction.State.APPROVED, user, row.version + 1
        row.save(update_fields=["state", "approved_by", "version"])
        audit("final.approve", row, actor, after={"state": row.state})
        return row

    @classmethod
    @transaction.atomic
    def execute(cls, user, action_id, quantity, evidence_id, operation_key):
        row = FinalAction.objects.select_for_update().select_related("asset").get(pk=action_id)
        if not AccessPolicy.can_edit_asset(user, row.asset):
            raise NotPermitted("Only the assigned custodian can record execution.")
        if not operation_key or len(operation_key) > 64:
            raise ValidationFailed("An operation key is required.")
        qty = Decimal(str(quantity))
        prior = FinalActionExecution.objects.filter(operation_key=operation_key).first()
        if prior:
            if prior.actor_id != user.pk or prior.action_id != row.pk or prior.quantity != qty or prior.evidence_id != evidence_id:
                raise ValidationFailed("This operation key was used for different details.")
            return prior
        if row.state not in (FinalAction.State.APPROVED, FinalAction.State.IN_PROGRESS):
            raise ValidationFailed("This action is not approved for execution.")
        cls.check_asset(row.asset)
        evidence = Attachment.objects.filter(pk=evidence_id, asset=row.asset, status="ACCEPTED", withdrawn_at__isnull=True).first()
        if evidence is None:
            raise ValidationFailed("Attach an accepted receipt or certificate to the asset first.")
        executed = row.executions.aggregate(total=Sum("quantity"))["total"] or Decimal(0)
        if qty <= 0 or qty + executed > row.quantity:
            raise ValidationFailed("Execution exceeds the approved quantity.")
        actor = ActorContext(user, operation_key=operation_key)
        InventoryLedger.execute_final(actor, claim_ref=row.claim_ref, quantity=qty, outcome=row.outcome,
                                      reference=row.claim_ref, evidence_refs=[f"attachment:{evidence.pk}"])
        result = FinalActionExecution.objects.create(action=row, quantity=qty, evidence=evidence, actor=user, operation_key=operation_key)
        row.state = FinalAction.State.COMPLETED if executed + qty == row.quantity else FinalAction.State.IN_PROGRESS
        row.version += 1
        row.save(update_fields=["state", "version"])
        audit("final.execute", row, actor, after={"state": row.state, "quantity": str(qty), "evidence": evidence.pk})
        return result
