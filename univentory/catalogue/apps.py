from django.apps import AppConfig


class CatalogueConfig(AppConfig):
    name = "catalogue"
    verbose_name = "Catalogue"

    def ready(self):
        from core import navigation
        from core.contracts import get_adapter
        from identity.policy import AccessPolicy

        from catalogue import services  # noqa: F401  (connects signal receivers)

        navigation.register("exchange", "catalogue:exchange", visible=AccessPolicy.can_browse_catalogue)

        # Fixture release queue occupies the Approvals slot only until Sinan's
        # workflow module registers the real Approvals destination.
        def fixture_queue_visible(user):
            return getattr(get_adapter("RELEASE_APPROVALS"), "is_test_adapter", False) and bool(
                AccessPolicy.departments_with_role(user, "DEPT_REP")
            )

        navigation.register("approvals", "catalogue:release_queue", visible=fixture_queue_visible)
