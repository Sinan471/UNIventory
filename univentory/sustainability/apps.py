from django.apps import AppConfig

IMPACT_ROLES = {"SUSTAINABILITY", "MANAGEMENT", "PROCUREMENT", "FINANCE", "AUDITOR", "REPORT_PUBLISHER", "DEPT_REP"}


def can_view_impact(user):
    from identity.policy import AccessPolicy

    return bool(AccessPolicy.role_codes(user) & IMPACT_ROLES)


class SustainabilityConfig(AppConfig):
    name = 'sustainability'

    def ready(self):
        from core.navigation import register

        register("impact", "sustainability:impact", visible=can_view_impact)
