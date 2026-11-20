from django.apps import AppConfig


class ExchangeConfig(AppConfig):
    name = "exchange"

    def ready(self):
        from core.navigation import register
        from identity.policy import AccessPolicy
        register("transfers", "transfer:queue", visible=AccessPolicy.has_any_role)
