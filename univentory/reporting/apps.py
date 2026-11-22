from django.apps import AppConfig


class ReportingConfig(AppConfig):
    name = 'reporting'

    def ready(self):
        from core.navigation import register

        def visible(user):
            from reporting.views import scope_departments

            return scope_departments(user) is not None

        register("reports", "reporting:index", visible=visible)
