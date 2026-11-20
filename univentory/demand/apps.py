from django.apps import AppConfig


class DemandConfig(AppConfig):
    name = "demand"

    def ready(self):
        from core.navigation import register
        from identity.policy import AccessPolicy
        register("requests", "demand:list", visible=AccessPolicy.has_any_role)
