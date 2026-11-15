from django.apps import AppConfig


class CareConfig(AppConfig):
    name = "care"

    def ready(self):
        from core.navigation import register
        from identity.models import Role
        from identity.policy import AccessPolicy
        register("care", "care:list", visible=lambda user: any(AccessPolicy.has_role(user, role) for role in (Role.CUSTODIAN, Role.MAINTENANCE, Role.DEPT_REP)))
