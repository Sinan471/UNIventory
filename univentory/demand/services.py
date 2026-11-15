from django.db import transaction
from core.contracts import ActorContext, DuplicateOperationConflict, NotPermitted, StaleVersion, ValidationFailed
from core.contracts.audit import audit
from identity.models import Role
from identity.policy import AccessPolicy
from .models import RequestEvent, RequestOperation, ResourceRequest


class DemandService:
    @staticmethod
    @transaction.atomic
    def save(user, data, *, request_id=None, expected_version=None, listing=None, submit=False, operation_key=""):
        department = data["department"]
        if not AccessPolicy.has_role(user, Role.REQUESTER, department):
            raise NotPermitted("You cannot submit requests for this department.")
        if data.get("urgent") and not (data.get("urgent_reason") or "").strip():
            raise ValidationFailed("Explain why this request is urgent.")
        payload = {k: getattr(v, "pk", v) for k, v in data.items() if k not in ("version", "operation_key")}
        payload.update(request_id=request_id, expected_version=expected_version, listing_id=getattr(listing, "pk", None), submit=submit)
        digest = ActorContext.payload_hash(payload)
        if operation_key:
            prior = RequestOperation.objects.filter(operation_key=operation_key).select_related("result").first()
            if prior:
                if prior.actor_id != user.pk or prior.payload_hash != digest:
                    raise DuplicateOperationConflict()
                return prior.result
        if request_id:
            item = ResourceRequest.objects.select_for_update().get(pk=request_id, requester=user)
            if item.state not in (ResourceRequest.State.DRAFT, ResourceRequest.State.RETURNED):
                raise ValidationFailed("Only drafts and returned requests can be edited.")
            if expected_version != item.version:
                raise StaleVersion("This request changed. Reload it before saving.")
            for key, value in data.items():
                if key not in ("version", "operation_key"):
                    setattr(item, key, value)
            item.version += 1
        else:
            item = ResourceRequest(requester=user, listing=listing, **{k: v for k, v in data.items() if k not in ("version", "operation_key")})
        item.state = ResourceRequest.State.SUBMITTED if submit else ResourceRequest.State.DRAFT
        item.full_clean()
        item.save()
        if operation_key:
            RequestOperation.objects.create(operation_key=operation_key, actor=user, payload_hash=digest, result=item)
        RequestEvent.objects.create(request=item, actor=user, action="Submitted" if submit else "Draft saved")
        audit("request.submit" if submit else "request.save", item, user, after={"state": item.state, "version": item.version})
        if submit:
            from notifications.services import NotificationService
            NotificationService.department_representatives(item.department, "A request is awaiting review in your department.", user)
        return item

    @staticmethod
    @transaction.atomic
    def cancel(user, request_id, expected_version):
        item = ResourceRequest.objects.select_for_update().get(pk=request_id, requester=user)
        if item.version != expected_version:
            raise StaleVersion("This request changed. Reload it before cancelling.")
        if item.state not in (ResourceRequest.State.DRAFT, ResourceRequest.State.SUBMITTED, ResourceRequest.State.RETURNED):
            raise ValidationFailed("This request cannot be cancelled.")
        if not AccessPolicy.has_role(user, Role.REQUESTER, item.department):
            raise NotPermitted("Your requester access is no longer active.")
        item.state = ResourceRequest.State.CANCELLED
        item.version += 1
        item.save(update_fields=["state", "version", "updated_at"])
        RequestEvent.objects.create(request=item, actor=user, action="Cancelled")
        audit("request.cancel", item, user, after={"state": item.state, "version": item.version})
        return item
