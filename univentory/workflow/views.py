from django.shortcuts import get_object_or_404, redirect, render
from core.contracts import DomainError, get_adapter
from core.web import active_role_required, domain_error_response
from demand.models import ResourceRequest
from identity.models import Role
from identity.policy import AccessPolicy
from .services import ApprovalService
from .models import ReleaseReview


@active_role_required
def queue(request):
    departments = AccessPolicy.departments_with_role(request.user, Role.DEPT_REP)
    items = ResourceRequest.objects.filter(department_id__in=departments, state=ResourceRequest.State.SUBMITTED).exclude(requester=request.user).select_related("requester", "department")
    releases = ReleaseReview.objects.none()
    if not getattr(get_adapter("RELEASE_APPROVALS"), "is_test_adapter", True):
        releases = ReleaseReview.objects.filter(listing__department_id__in=departments, status="pending").exclude(requested_by=request.user).select_related("listing", "listing__department")
    return render(request, "workflow/queue.html", {"items": items, "releases": releases, "nav_current": "approvals"})


@active_role_required
def review(request, pk):
    departments = AccessPolicy.departments_with_role(request.user, Role.DEPT_REP)
    item = get_object_or_404(ResourceRequest.objects.select_related("requester", "department"), pk=pk, department_id__in=departments)
    if request.method == "POST":
        try:
            version = int(request.POST.get("version", ""))
        except ValueError:
            return render(request, "core/error.html", {"status": 400, "message": "Invalid request version."}, status=400)
        try:
            ApprovalService.decide_request(request.user, pk, version, request.POST.get("decision", ""), request.POST.get("reason", ""))
        except DomainError as exc:
            return domain_error_response(request, exc, "workflow/review.html", {"item": item})
        return redirect("workflow:queue")
    return render(request, "workflow/review.html", {"item": item, "nav_current": "approvals"})


@active_role_required
def release_review(request, pk):
    from catalogue.services import CatalogueService
    departments = AccessPolicy.departments_with_role(request.user, Role.DEPT_REP)
    row = get_object_or_404(ReleaseReview.objects.select_related("listing", "listing__department", "requested_by"), pk=pk, listing__department_id__in=departments)
    adapter = get_adapter("RELEASE_APPROVALS")
    if getattr(adapter, "is_test_adapter", True):
        return render(request, "core/error.html", {"status": 404}, status=404)
    if request.method == "POST":
        try:
            version = int(request.POST.get("version", ""))
        except ValueError:
            return render(request, "core/error.html", {"status": 400}, status=400)
        try:
            adapter.decide(listing_id=row.listing_id, decider=request.user, expected_version=version,
                           status=request.POST.get("decision", ""), reason=request.POST.get("reason", ""))
            CatalogueService.sync_release_outcome(row.listing)
        except DomainError as exc:
            return domain_error_response(request, exc, "workflow/release_review.html", {"review": row})
        return redirect("workflow:queue")
    return render(request, "workflow/release_review.html", {"review": row, "nav_current": "approvals"})
