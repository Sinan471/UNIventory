from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "notifications"

    def ready(self):
        from core.navigation import register
        from identity.policy import AccessPolicy
        register("notifications", "notifications:list", visible=AccessPolicy.has_any_role)
