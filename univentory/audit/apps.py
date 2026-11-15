from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "audit"

    def ready(self):
        from core.navigation import register
        from identity.models import Role
        from identity.policy import AccessPolicy
        register("audit", "audit:list", visible=lambda user: any(g.role == Role.AUDITOR and g.department_id is None for g in AccessPolicy.grants(user)))
