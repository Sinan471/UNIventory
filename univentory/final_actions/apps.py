from django.apps import AppConfig


class FinalActionsConfig(AppConfig):
    name = "final_actions"

    def ready(self):
        from core.navigation import register
        from identity.models import Role
        from identity.policy import AccessPolicy

        register("final_actions", "final_actions:list",
                 visible=lambda user: AccessPolicy.has_role(user, Role.DEPT_REP) or AccessPolicy.has_role(user, Role.CUSTODIAN))
