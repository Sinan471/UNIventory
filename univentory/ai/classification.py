
from decimal import Decimal

from catalogue.services import CatalogueQueryService, CatalogueService


class ClassificationService:
    @staticmethod
    def suggest_category(asset):
        if not asset.title and not asset.description:
            return {
                "status": "INSUFFICIENT_DATA",
                "category_id": None,
                "reason": "Asset information is missing."
            }

        if not asset.category_id:
            return {
                "status": "REVIEW_REQUIRED",
                "category_id": None,
                "reason": "No existing category is assigned. Manual classification is required."
            }

        return {
            "status": "REVIEW_REQUIRED",
            "category_id": asset.category_id,
            "category_name": asset.category.name,
            "reason": "The existing registered category is suggested for review."
        }


class RankingService:
    CONDITION_SCORES = {
        "POOR": 0.25,
        "FAIR": 0.50,
        "GOOD": 0.75,
        "EXCELLENT": 1.00,
    }

    @staticmethod
    def text_similarity(need_title, asset_title, asset_description=""):
        need_words = set((need_title or "").lower().split())
        asset_words = set(
            ((asset_title or "") + " " + (asset_description or "")).lower().split()
        )

        if not need_words:
            return 0.0

        return len(need_words & asset_words) / len(need_words)

    @classmethod
    def rank(cls, listing, need_title, required_quantity):
        required_quantity = Decimal(str(required_quantity))
        free_quantity = CatalogueService.free_quantity(listing)

        similarity = cls.text_similarity(
            need_title,
            listing.asset.title,
            listing.asset.description
        )

        quantity_score = min(
            free_quantity / required_quantity, Decimal("1")
        ) if required_quantity > 0 else Decimal("0")

        condition = getattr(listing.portion, "condition", "UNKNOWN")
        condition_score = Decimal(
            str(cls.CONDITION_SCORES.get(condition, 0))
        )

        # These factors remain unknown until verified location,
        # cost and environmental evidence are integrated.
        location_score = Decimal("0.5")
        cost_score = Decimal("0.5")
        environmental_score = Decimal("0.5")

        functional_score = Decimal(str(similarity))

        total = (
            functional_score * Decimal("0.40")
            + quantity_score * Decimal("0.20")
            + condition_score * Decimal("0.15")
            + location_score * Decimal("0.10")
            + cost_score * Decimal("0.10")
            + environmental_score * Decimal("0.05")
        ) * Decimal("100")

        return {
            "listing_id": listing.pk,
            "title": listing.title,
            "asset_title": listing.asset.title,
            "category": listing.asset.category.name,
            "free_quantity": str(free_quantity),
            "score": round(float(total), 2),
            "factors": {
                "functional_fit": round(similarity, 3),
                "quantity_coverage": round(float(quantity_score), 3),
                "condition": float(condition_score),
                "location_timing": "UNKNOWN",
                "reuse_cost": "UNKNOWN",
                "environmental_evidence": "UNKNOWN",
            },
            "reason": (
                "Candidate retrieved from the visible published catalogue. "
                "Some ranking factors still require verified evidence."
            )
        }


class MatchingService:
    @staticmethod
    def get_candidates(user, need_title, required_quantity=1, category_id=None):
        params = {
            "q": need_title,
            "min_qty": str(required_quantity),
            "availability": "available",
            "sort": "free",
        }

        if category_id:
            params["category"] = category_id

        listings = CatalogueQueryService.search(user, params)

        results = []

        for listing in listings:
            free_quantity = CatalogueService.free_quantity(listing)

            if free_quantity < Decimal(str(required_quantity)):
                continue

            results.append(
                RankingService.rank(
                    listing,
                    need_title,
                    required_quantity
                )
            )

        results.sort(key=lambda item: item["score"], reverse=True)

        return results[:5]
