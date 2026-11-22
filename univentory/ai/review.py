
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import MatchRecommendation, RecommendationReview


class RecommendationReviewService:

    @staticmethod
    @transaction.atomic
    def record_decision(
        recommendation_id,
        reviewer,
        decision,
        reason="",
        overridden_listing=None
    ):
        try:
            recommendation = (
                MatchRecommendation.objects
                .select_for_update()
                .get(pk=recommendation_id)
            )
        except MatchRecommendation.DoesNotExist:
            raise ValidationError("Recommendation does not exist.")

        if not reviewer or not reviewer.is_authenticated:
            raise ValidationError("An authenticated reviewer is required.")

        valid_decisions = RecommendationReview.Decision.values

        if decision not in valid_decisions:
            raise ValidationError("Invalid recommendation decision.")

        if decision == RecommendationReview.Decision.OVERRIDDEN:
            if overridden_listing is None:
                raise ValidationError(
                    "An alternative listing is required for an override."
                )
        elif overridden_listing is not None:
            raise ValidationError(
                "An alternative listing is only allowed for an override."
            )

        return RecommendationReview.objects.create(
            recommendation=recommendation,
            reviewer=reviewer,
            decision=decision,
            reason=reason,
            overridden_listing=overridden_listing
        )

