import uuid
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from core.contracts import DomainError
from core.web import active_role_required, domain_error_response
from identity.models import Role
from identity.policy import AccessPolicy
from inventory.models import AssetPortion
from .forms import ExecuteForm, ProposalForm
from .models import FinalAction
from .services import FinalActionService


def visible(user):
    reps = AccessPolicy.departments_with_role(user, Role.DEPT_REP)
    custodians = AccessPolicy.departments_with_role(user, Role.CUSTODIAN)
    return FinalAction.objects.filter(Q(department_id__in=reps) | Q(asset__custodian=user, department_id__in=custodians))


@active_role_required
def action_list(request):
    return render(request, "final_actions/list.html", {"items": visible(request.user).select_related("asset", "department")})


@active_role_required
def propose(request, pk):
    portion = get_object_or_404(AssetPortion.objects.select_related("asset"), pk=pk, is_active_leaf=True,
        asset__custodian=request.user, asset__department_id__in=AccessPolicy.departments_with_role(request.user, Role.CUSTODIAN))
    form = ProposalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            row = FinalActionService.propose(request.user, pk, **form.cleaned_data)
        except DomainError as exc:
            return domain_error_response(request, exc, "final_actions/propose.html", {"portion": portion, "form": form})
        return redirect("final_actions:detail", pk=row.pk)
    return render(request, "final_actions/propose.html", {"portion": portion, "form": form})


@active_role_required
def detail(request, pk):
    row = get_object_or_404(visible(request.user).select_related("asset", "department"), pk=pk)
    can_approve = AccessPolicy.has_role(request.user, Role.DEPT_REP, row.department) and request.user.pk != row.proposed_by_id
    can_execute = AccessPolicy.can_edit_asset(request.user, row.asset)
    form = ExecuteForm(request.POST or None, asset=row.asset, initial={"operation_key": uuid.uuid4().hex})
    if request.method == "POST":
        try:
            if request.POST.get("action") == "approve":
                try:
                    version = int(request.POST.get("version", ""))
                except ValueError:
                    return render(request, "core/error.html", {"status": 400}, status=400)
                FinalActionService.approve(request.user, pk, version)
            elif request.POST.get("action") == "execute" and form.is_valid():
                FinalActionService.execute(request.user, pk, form.cleaned_data["quantity"], form.cleaned_data["evidence"].pk, form.cleaned_data["operation_key"])
            else:
                return render(request, "final_actions/detail.html", {"item": row, "form": form, "can_approve": can_approve, "can_execute": can_execute}, status=422)
        except DomainError as exc:
            return domain_error_response(request, exc, "final_actions/detail.html", {"item": row, "form": form, "can_approve": can_approve, "can_execute": can_execute})
        return redirect("final_actions:detail", pk=pk)
    return render(request, "final_actions/detail.html", {"item": row, "form": form, "can_approve": can_approve, "can_execute": can_execute})
