from django.apps import AppConfig


class DemandConfig(AppConfig):
    name = "demand"

    def ready(self):
        from core.navigation import register
        from identity.policy import AccessPolicy
        register("requests", "demand:list", visible=lambda user: AccessPolicy.has_role(user, "REQUESTER"))
