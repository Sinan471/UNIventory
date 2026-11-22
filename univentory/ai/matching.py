
from decimal import Decimal, InvalidOperation

from catalogue.services import CatalogueQueryService
from inventory.models import Condition


class MatchingService:

    RANKING_VERSION = "1.1"

    STOPWORDS = set(
        "a an and are as at be by for from in into is it of on or our the their this to with we need needs "
        "new use used using two three four five six some each per one any all more extra spare second".split()
    )
    # Small, versioned vocabulary so equivalent terms meet (AI-03). Not a model.
    SYNONYMS = {
        "screen": "monitor", "display": "monitor", "pc": "desktop", "computer": "desktop", "notebook": "laptop",
        "seat": "chair", "seating": "chair", "table": "desk", "workstation": "desk", "board": "whiteboard",
        "scope": "microscope", "projection": "projector", "beamer": "projector", "print": "printer",
    }

    @classmethod
    def _words(cls, value):
        import re
        out = set()
        for word in re.findall(r"[a-z0-9]+", str(value or "").lower()):
            if word in cls.STOPWORDS or len(word) < 2:
                continue
            if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
                word = word[:-1]
            out.add(cls.SYNONYMS.get(word, word))
        return out

    @classmethod
    def _functional_fit(cls, request, listing):
        """Share of the need's key terms found in the listing (0-1).

        Title and specifications carry the need; the purpose adds context but
        cannot dilute the score. Version 1.1 of the rule-based fallback.
        """
        asset = listing.asset
        available = cls._words(" ".join([
            listing.title or "", listing.public_description or "", asset.title or "", asset.description or "",
            asset.subcategory or "", " ".join(asset.tags or []), asset.category.name if asset.category_id else "",
        ]))
        core = cls._words(f"{request.title or ''} {request.specifications or ''}")
        context = cls._words(request.purpose or "") - core
        if not core and not context:
            return 0.0
        core_hit = len(core & available) / min(len(core), 4) if core else 0.0
        context_hit = len(context & available) / min(len(context), 6) if context else 0.0
        return round(min(1.0, 0.75 * core_hit + 0.25 * context_hit), 3)

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

        # Highest score first; ties broken by stable listing ID (RP-1).
        results.sort(key=lambda item: (-item["score"], item["listing_id"]))

        return results[:5]

    @classmethod
    def for_request(cls, user, request, limit=5):
        """Rank permitted, available listings for a saved need (AI-03 to AI-06).

        Eligibility is applied first by the catalogue's scoped search (access,
        release, safety, free stock). Candidates with no functional overlap are
        not recommended. Partial supply is labelled, never hidden. The result
        is a ranking aid; it allocates nothing.
        """
        outstanding = Decimal(str(request.outstanding_quantity))
        if outstanding <= 0:
            return []
        listings = CatalogueQueryService.search(user, {"availability": "available", "sort": "newest"})
        results = []
        for listing in listings[:200]:
            # Mandatory compatibility before ranking (AI-04): category and minimum condition.
            if request.category_id and listing.asset.category_id != request.category_id:
                continue
            order = ["POOR", "FAIR", "GOOD", "EXCELLENT"]
            condition = getattr(listing.portion, "condition", None)
            if request.min_condition and (condition not in order or order.index(condition) < order.index(request.min_condition)):
                continue
            ranked = cls._rank_listing(listing, outstanding, request)
            if ranked["factors"]["functional_fit"] < 0.25:
                continue
            ranked["partial"] = Decimal(str(listing.free_qty)) < outstanding
            known = 6 - len(ranked["missing_evidence"])
            ranked["evidence_status"] = "Sufficient evidence" if known / 6 >= 0.8 else "Needs review"
            ranked["coverage"] = f"{known} of 6 factors recorded"
            results.append(ranked)
        results.sort(key=lambda item: (-item["score"], item["listing_id"]))
        return results[:limit]
