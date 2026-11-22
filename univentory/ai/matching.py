
from decimal import Decimal, InvalidOperation

from catalogue.services import CatalogueQueryService
from inventory.models import Condition


class MatchingService:

    RANKING_VERSION = "1.0"

    @staticmethod
    def _words(value):
        import re
        return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))

    @classmethod
    def _functional_fit(cls, request, listing):
        required_text = " ".join([
            request.title or "",
            request.purpose or "",
            request.specifications or "",
        ])

        asset = listing.asset

        available_text = " ".join([
            listing.title or "",
            listing.public_description or "",
            asset.title or "",
            asset.description or "",
            asset.subcategory or "",
            " ".join(asset.tags or []),
        ])

        required_words = cls._words(required_text)
        available_words = cls._words(available_text)

        if not required_words:
            return 0.0

        return len(required_words & available_words) / len(required_words)

    @staticmethod
    def _condition_score(listing):
        condition = getattr(listing.portion, "condition", None)

        scores = {
            Condition.POOR: 0.25,
            Condition.FAIR: 0.50,
            Condition.GOOD: 0.75,
            Condition.EXCELLENT: 1.0,
        }

        return scores.get(condition)

    @classmethod
    def _rank_listing(cls, listing, required_quantity, request=None):
        free_quantity = Decimal(str(listing.free_qty))

        quantity_coverage = min(
            free_quantity / required_quantity,
            Decimal("1")
        )

        if request:
            functional_fit = cls._functional_fit(request, listing)
        else:
            functional_fit = 0.0

        condition_score = cls._condition_score(listing)

        # Unknown evidence is kept as None, not treated as a verified zero.
        factors = {
            "functional_fit": functional_fit,
            "quantity_coverage": float(quantity_coverage),
            "condition": condition_score,
            "location_timing": None,
            "reuse_cost": None,
            "environmental_evidence": None,
        }

        weights = {
            "functional_fit": 0.40,
            "quantity_coverage": 0.20,
            "condition": 0.15,
            "location_timing": 0.10,
            "reuse_cost": 0.10,
            "environmental_evidence": 0.05,
        }

        known_weight = sum(
            weights[name]
            for name, value in factors.items()
            if value is not None
        )

        score = (
            100 * sum(
                weights[name] * value
                for name, value in factors.items()
                if value is not None
            ) / known_weight
            if known_weight else 0
        )

        reasons = [
            f"Functional fit: {functional_fit:.0%}.",
            f"Quantity coverage: {quantity_coverage:.0%}.",
        ]

        if condition_score is None:
            reasons.append("Condition evidence is unavailable.")
        else:
            reasons.append(f"Condition score: {condition_score:.0%}.")

        missing_evidence = [
            name for name, value in factors.items()
            if value is None
        ]

        return {
            "listing_id": listing.pk,
            "asset_id": listing.asset_id,
            "title": listing.title,
            "description": listing.public_description,
            "category": listing.asset.category.name,
            "department": str(listing.department),
            "free_quantity": free_quantity,
            "score": round(score, 2),
            "factors": factors,
            "missing_evidence": missing_evidence,
            "reasons": reasons,
            "ranking_version": cls.RANKING_VERSION,
        }

    @classmethod
    def get_candidates(
        cls,
        user,
        needed_category_id,
        required_quantity=1,
        request=None
    ):
        try:
            quantity = Decimal(str(required_quantity))
        except (InvalidOperation, ValueError):
            raise ValueError("Invalid required quantity.")

        if quantity <= 0:
            raise ValueError("Required quantity must be greater than zero.")

        listings = CatalogueQueryService.search(
            user,
            {
                "category": needed_category_id,
                "min_qty": str(quantity),
                "availability": "available",
                "sort": "free",
            }
        )

        results = []

        for listing in listings:
            free_quantity = Decimal(str(listing.free_qty))

            if free_quantity < quantity:
                continue

            results.append(
                cls._rank_listing(listing, quantity, request)
            )

        results.sort(
            key=lambda item: (
                item["score"],
                item["listing_id"]
            ),
        )

        return results[:5]
