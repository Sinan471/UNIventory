from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Core platform"

    def ready(self):
        from core import navigation
        from identity.policy import AccessPolicy

        # Every role gets a workbench: the tasks waiting on that person.
        navigation.register("home", "core:home", visible=AccessPolicy.has_any_role)
