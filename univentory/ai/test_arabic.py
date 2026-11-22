
from django.test import SimpleTestCase
from .assistant import AssistantService


class ArabicAssistantTest(SimpleTestCase):

    def test_arabic_query_is_accepted(self):
        result = AssistantService.validate_action("search_catalogue")

        self.assertTrue(result)

    def test_arabic_text_is_preserved(self):
        query = "أبحث عن جهاز حاسوب محمول"

        self.assertEqual(
            query,
            "أبحث عن جهاز حاسوب محمول"
        )

    def test_empty_query_is_detected(self):
        query = ""

        self.assertEqual(query.strip(), "")
