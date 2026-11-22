from django import forms
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Q
from core.contracts import DomainError
from core.web import active_role_required, domain_error_response
from inventory.models import AssetPortion
from identity.models import Role
from identity.policy import AccessPolicy
from .models import DefectReport, MaintenanceCase
from inventory.models import Attachment
from .services import CareService


class DefectForm(forms.Form):
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Describe the defect")


@active_role_required
def care_list(request):
    departments = AccessPolicy.departments_with_role(request.user, Role.CUSTODIAN)
    portions = AssetPortion.objects.filter(asset__custodian=request.user, asset__department_id__in=departments, is_active_leaf=True).select_related("asset")
    maintenance = AccessPolicy.departments_with_role(request.user, Role.MAINTENANCE)
    representatives = AccessPolicy.departments_with_role(request.user, Role.DEPT_REP)
    reports = DefectReport.objects.filter(Q(reported_by=request.user, asset__department_id__in=departments) | Q(portion__department_id__in=maintenance)).select_related("asset").distinct()
    cases = MaintenanceCase.objects.filter(Q(portion__department_id__in=maintenance + representatives) | Q(defect__asset__custodian=request.user, portion__department_id__in=departments)).select_related("defect__asset").distinct()
    from core import charts
    case_list = list(cases)
    stats = {"open": sum(1 for c in case_list if c.state != MaintenanceCase.State.CLOSED),
             "approval": sum(1 for c in case_list if c.state == MaintenanceCase.State.AWAITING_APPROVAL),
             "success": sum(1 for c in case_list if c.outcome in ("SUCCESS", "NO_REPAIR")),
             "failed": sum(1 for c in case_list if c.outcome == "FAILED"),
             "reports": len(list(reports))}
    seg = [("Successful", stats["success"]), ("Failed", stats["failed"]), ("In progress", stats["open"])]
    return render(request, "care/list.html", {"portions": portions, "reports": reports, "cases": case_list,
                  "maintenance_departments": maintenance, "nav_current": "care", "stats": stats,
                  "donut": charts.donut(seg, center_value=str(len(case_list)), center_label="cases"),
                  "legend": charts.legend([n for n, _ in seg], [v for _, v in seg])})


@active_role_required
def report(request, pk):
    portion = get_object_or_404(AssetPortion.objects.select_related("asset"), pk=pk, asset__custodian=request.user,
        asset__department_id__in=AccessPolicy.departments_with_role(request.user, Role.CUSTODIAN), is_active_leaf=True)
    form = DefectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            CareService.report_defect(request.user, pk, form.cleaned_data["description"])
        except DomainError as exc:
            return domain_error_response(request, exc, "care/report.html", {"portion": portion, "form": form})
        return redirect("care:list")
    return render(request, "care/report.html", {"portion": portion, "form": form, "nav_current": "care"})


@active_role_required
def inspect(request, pk):
    row = get_object_or_404(DefectReport.objects.select_related("asset"), pk=pk, portion__department_id__in=AccessPolicy.departments_with_role(request.user, Role.MAINTENANCE))
    form = DefectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            case = CareService.inspect(request.user, pk, form.cleaned_data["description"])
        except DomainError as exc:
            return domain_error_response(request, exc, "care/inspect.html", {"report": row, "form": form})
        return redirect("care:case", pk=case.pk)
    return render(request, "care/inspect.html", {"report": row, "form": form})


@active_role_required
def case_detail(request, pk):
    maintenance = AccessPolicy.departments_with_role(request.user, Role.MAINTENANCE)
    reps = AccessPolicy.departments_with_role(request.user, Role.DEPT_REP)
    custodians = AccessPolicy.departments_with_role(request.user, Role.CUSTODIAN)
    row = get_object_or_404(MaintenanceCase.objects.select_related("defect__asset", "portion"), Q(portion__department_id__in=maintenance + reps) | Q(defect__asset__custodian=request.user, portion__department_id__in=custodians), pk=pk)
    evidence = Attachment.objects.filter(asset=row.defect.asset, status="ACCEPTED", withdrawn_at__isnull=True)
    if request.method == "POST":
        try:
            version = int(request.POST.get("version", ""))
            action = request.POST.get("action", "")
            if action == "request_work":
                CareService.request_work(request.user, pk, version, request.POST.get("notes", ""))
            elif action == "approve_work":
                CareService.approve_work(request.user, pk, version)
            elif action == "finish_work":
                CareService.finish_work(request.user, pk, version, request.POST.get("notes", ""))
            elif action in ("success", "failed"):
                CareService.verify(request.user, pk, version, action == "success", int(request.POST.get("evidence", "")))
            elif action == "no_repair":
                CareService.no_repair_needed(request.user, pk, version, int(request.POST.get("evidence", "")))
            elif action == "rework":
                if row.version != version:
                    from core.contracts import StaleVersion
                    raise StaleVersion()
                new_case = CareService.inspect(request.user, row.defect_id, request.POST.get("notes", ""), previous_case_id=row.pk)
                return redirect("care:case", pk=new_case.pk)
            else:
                return render(request, "core/error.html", {"status": 400}, status=400)
        except ValueError:
            return render(request, "core/error.html", {"status": 400, "message": "Invalid submitted value."}, status=400)
        except DomainError as exc:
            return domain_error_response(request, exc, "care/case.html", {"item": row, "evidence": evidence})
        return redirect("care:case", pk=pk)
    return render(request, "care/case.html", {"item": row, "evidence": evidence, "nav_current": "care"})
