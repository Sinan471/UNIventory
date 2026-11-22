
from django.test import SimpleTestCase

from ai.advice import ActionAdviceService
from ai.assistant import AssistantService


class ActionAdviceTest(SimpleTestCase):

    def test_good_condition_suggests_reuse(self):
        asset = type("Asset", (), {"condition": "GOOD"})()

        result = ActionAdviceService.compare_options(asset)

        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertIn(
            "REUSE",
            [item["action"] for item in result["options"]]
        )

    def test_missing_asset(self):
        result = ActionAdviceService.compare_options(None)

        self.assertEqual(result["status"], "INSUFFICIENT_DATA")


class AssistantTest(SimpleTestCase):

    def test_request_preview_requires_confirmation(self):
        result = AssistantService.create_request_preview(
            "Laptop",
            "For coursework",
            2
        )

        self.assertEqual(result["status"], "AWAITING_CONFIRMATION")
        self.assertFalse(result["submitted"])

    def test_invalid_quantity(self):
        with self.assertRaises(ValueError):
            AssistantService.create_request_preview(
                "Laptop",
                "For coursework",
                0
            )

    def test_blocked_action(self):
        self.assertFalse(AssistantService.validate_action("approve"))

    def test_allowed_action(self):
        self.assertTrue(AssistantService.validate_action("search"))
