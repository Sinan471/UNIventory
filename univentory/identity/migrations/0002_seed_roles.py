"""Seed the documented application roles (Phase 4-5, Section 7.2).

Roles are part of the access matrix; permissions are enforced in code by
AccessPolicy and each module's service, not by these rows alone.
"""
from django.db import migrations

ROLES = [
    # code, name, Arabic name, requires department, specialist, description
    ("REQUESTER", "Requester", "مقدم الطلب", True, False, "Submits and tracks departmental needs."),
    ("DEPT_REP", "Department Representative", "ممثل القسم", True, False,
     "Independent need, release and reservation decisions for the department."),
    ("CUSTODIAN", "Asset Custodian", "أمين الأصول", True, False, "Registers and maintains assigned asset records."),
    ("RECEIVER", "Assigned Receiver", "المستلم المعيّن", True, False, "Confirms assigned receipts."),
    ("APPROVER", "Authorised Approver", "المعتمد المفوّض", True, False,
     "Approves assigned transfers, service expenditure and final actions."),
    ("MAINTENANCE", "Maintenance Staff", "فريق الصيانة", True, True, "Inspection, service work and verification."),
    ("PROCUREMENT", "Procurement Officer", "مسؤول المشتريات", False, True, "Purchase baselines and specialist review."),
    ("FINANCE", "Finance Officer", "المسؤول المالي", False, True, "Cost evidence and specialist review."),
    ("CAMPUS_USER", "Campus User", "مستخدم الحرم", False, False, "Baseline catalogue access only."),
    ("SUSTAINABILITY", "Sustainability Officer", "مسؤول الاستدامة", False, True, "Impact factors and review."),
    ("MANAGEMENT", "University Management", "إدارة الجامعة", False, False, "Summary reports."),
    ("AUDITOR", "Auditor", "المدقق", False, False, "Assigned audit history and export."),
    ("SYSADMIN", "System Administrator", "مسؤول النظام", False, False,
     "Roles and reference data. No business approval authority unless separately assigned."),
    ("REPORT_PUBLISHER", "Report Publisher", "ناشر التقارير", False, False,
     "Reviews and publishes AI report narratives. Confers no asset approval power."),
]


def seed(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    for code, name, name_ar, needs_dept, specialist, description in ROLES:
        Role.objects.update_or_create(
            code=code,
            defaults={"name": name, "name_ar": name_ar, "requires_department": needs_dept,
                      "is_specialist": specialist, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("identity", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
