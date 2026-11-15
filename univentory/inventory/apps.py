from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "inventory"
    verbose_name = "Inventory"

    def ready(self):
        from core import navigation
        from identity.models import Role
        from identity.policy import AccessPolicy

        def visible(user):
            codes = AccessPolicy.role_codes(user)
            return bool(codes & {Role.CUSTODIAN, Role.DEPT_REP})

        navigation.register("assets", "inventory:my_assets", visible=visible)
