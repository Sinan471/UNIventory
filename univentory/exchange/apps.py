from django.apps import AppConfig


class ExchangeConfig(AppConfig):
    name = "exchange"

    def ready(self):
        from core.navigation import register
        from identity.policy import AccessPolicy
        register("transfers", "transfer:queue", visible=lambda user: bool(AccessPolicy.role_codes(user) & {"REQUESTER", "DEPT_REP", "CUSTODIAN", "RECEIVER"}))
