from django.apps import AppConfig


class WorkflowConfig(AppConfig):
    name = "workflow"

    def ready(self):
        from core.navigation import register
        from identity.models import Role
        from identity.policy import AccessPolicy
        register("approvals", "workflow:queue", visible=lambda user: AccessPolicy.has_role(user, Role.DEPT_REP))
