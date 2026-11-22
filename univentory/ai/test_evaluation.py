
from django.test import SimpleTestCase
from .evaluation import EvaluationService


class EvaluationServiceTest(SimpleTestCase):

    def test_classification_accuracy(self):
        result = EvaluationService.classification_accuracy(
            ["Laptop", "Chair", "Table"],
            ["Laptop", "Chair", "Desk"],
        )

        self.assertEqual(result["accuracy"], 66.67)

    def test_matching_usefulness(self):
        results = [
            {"listing_id": 1},
            {"listing_id": 2},
            {"listing_id": 3},
        ]

        result = EvaluationService.matching_usefulness(
            results, [1, 3]
        )

        self.assertEqual(result["useful_matches"], 2)
        self.assertEqual(result["usefulness_rate"], 66.67)

    def test_classic_vs_ai(self):
        classic = [{"listing_id": 1}, {"listing_id": 2}]
        ai = [{"listing_id": 1}, {"listing_id": 3}]

        result = EvaluationService.compare_classic_vs_ai(
            classic, ai, [1, 3]
        )

        self.assertEqual(result["improvement"], 50.0)

    def test_empty_classification_data(self):
        result = EvaluationService.classification_accuracy([], [])

        self.assertEqual(result["status"], "NOT_APPLICABLE")

