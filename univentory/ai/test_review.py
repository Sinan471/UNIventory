
from django.test import TestCase
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from unittest.mock import MagicMock, patch

from ai.models import RecommendationReview
from ai.review import RecommendationReviewService


class RecommendationReviewTest(TestCase):

    def setUp(self):
        self.user = MagicMock()
        self.user.is_authenticated = True

        self.recommendation = MagicMock()
        self.recommendation.pk = 1

    @patch("ai.review.RecommendationReview.objects.create")
    @patch("ai.review.MatchRecommendation.objects.select_for_update")
    def test_accept_recommendation(self, mock_query, mock_create):
        mock_query.return_value.get.return_value = self.recommendation
        mock_create.return_value.decision = "ACCEPTED"

        review = RecommendationReviewService.record_decision(
            1, self.user, RecommendationReview.Decision.ACCEPTED
        )

        self.assertEqual(review.decision, "ACCEPTED")

    @patch("ai.review.RecommendationReview.objects.create")
    @patch("ai.review.MatchRecommendation.objects.select_for_update")
    def test_reject_recommendation(self, mock_query, mock_create):
        mock_query.return_value.get.return_value = self.recommendation
        mock_create.return_value.decision = "REJECTED"

        review = RecommendationReviewService.record_decision(
            1, self.user, RecommendationReview.Decision.REJECTED
        )

        self.assertEqual(review.decision, "REJECTED")

    @patch("ai.review.MatchRecommendation.objects.select_for_update")
    def test_invalid_decision(self, mock_query):
        mock_query.return_value.get.return_value = self.recommendation

        with self.assertRaises(ValidationError):
            RecommendationReviewService.record_decision(
                1, self.user, "INVALID"
            )

    @patch("ai.review.MatchRecommendation.objects.select_for_update")
    def test_override_requires_alternative(self, mock_query):
        mock_query.return_value.get.return_value = self.recommendation

        with self.assertRaises(ValidationError):
            RecommendationReviewService.record_decision(
                1, self.user, RecommendationReview.Decision.OVERRIDDEN
            )
