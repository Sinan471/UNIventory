from django.db import transaction
from core.contracts import NotPermitted, StaleVersion, ValidationFailed
from core.contracts.audit import audit
from demand.models import RequestEvent, ResourceRequest
from identity.models import Role
from identity.policy import AccessPolicy
from .models import ApprovalDecision


class ApprovalService:
    @staticmethod
    @transaction.atomic
    def decide_request(user, request_id, expected_version, decision, reason=""):
        item = ResourceRequest.objects.select_for_update().get(pk=request_id)
        if not AccessPolicy.has_role(user, Role.DEPT_REP, item.department):
            raise NotPermitted("Only the department representative can review this request.")
        if item.requester_id == user.pk:
            raise NotPermitted("You cannot approve your own request.")
        if item.version != expected_version:
            raise StaleVersion("This request changed. Reload it before reviewing.")
        if item.state != ResourceRequest.State.SUBMITTED:
            raise ValidationFailed("This request is no longer awaiting approval.")
        states = {"approve": ResourceRequest.State.APPROVED, "return": ResourceRequest.State.RETURNED,
                  "reject": ResourceRequest.State.REJECTED}
        if decision not in states:
            raise ValidationFailed("Choose a valid decision.")
        if decision != "approve" and not reason.strip():
            raise ValidationFailed("Give a reason for returning or rejecting this request.")
        ApprovalDecision.objects.create(request=item, request_version=item.version, actor=user, decision=decision, reason=reason.strip())
        item.state = states[decision]
        item.version += 1
        item.save(update_fields=["state", "version", "updated_at"])
        RequestEvent.objects.create(request=item, actor=user, action=item.get_state_display()[:32])
        audit("request.review", item, user, after={"state": item.state, "decision": decision}, reason=reason)
        from notifications.services import NotificationService
        NotificationService.notify(item.requester, "A decision was recorded on one of your requests. Open My Requests to review it.")
        return item
