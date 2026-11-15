from django.apps import AppConfig


class IdentityConfig(AppConfig):
    name = "identity"
    verbose_name = "Identity and reference data"

    def ready(self):
        from core import navigation
        from identity.policy import AccessPolicy

        navigation.register("admin", "identity:admin_home", visible=AccessPolicy.is_sysadmin)
