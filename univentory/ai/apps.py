from django.apps import AppConfig


class AiConfig(AppConfig):
    name = 'ai'

    def ready(self):
        from core.navigation import register
        from identity.policy import AccessPolicy

        register("assistant", "ai:assistant", visible=AccessPolicy.has_any_role)
