
from decimal import Decimal, InvalidOperation
from demand.services import DemandService
from catalogue.services import CatalogueQueryService


class AssistantService:

    ALLOWED_ACTIONS = {
        "search",
        "search_catalogue",
        "create_request_preview",
    }

    @staticmethod
    def search_catalogue(user, query):
        if not query or not query.strip():
            return []

        listings = CatalogueQueryService.search(
            user,
            {
                "q": query.strip(),
                "availability": "available",
                "sort": "free",
            }
        )

        results = []

        for listing in listings[:5]:
            results.append({
                "listing_id": listing.pk,
                "title": listing.title,
                "description": listing.public_description,
                "category": listing.asset.category.name,
                "available_quantity": str(listing.free_qty),
            })

        return results

    @classmethod
    def validate_action(cls, action):
        if not isinstance(action, str):
            return False

        return action.strip().casefold() in cls.ALLOWED_ACTIONS

    @staticmethod
    def create_request_preview(
        title,
        purpose,
        quantity,
        specifications="",
        needed_by=None,
    ):
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Request title is required.")

        if not isinstance(purpose, str) or not purpose.strip():
            raise ValueError("Request purpose is required.")

        try:
            if isinstance(quantity, bool):
                raise InvalidOperation

            quantity = Decimal(str(quantity))

        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Invalid request quantity.")

        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")

        return {
            "title": title.strip(),
            "purpose": purpose.strip(),
            "quantity": quantity,
            "specifications": specifications,
            "needed_by": needed_by,
            "status": "AWAITING_CONFIRMATION",
            "submitted": False,
        }

    @staticmethod
    def confirm_request(
        user,
        preview,
        department,
        *,
        confirmed=False,
        operation_key="",
    ):
        if confirmed is not True:
            raise ValueError("Explicit confirmation is required.")

        if not isinstance(preview, dict):
            raise ValueError("Invalid request preview.")

        if preview.get("status") != "AWAITING_CONFIRMATION":
            raise ValueError("Invalid or expired request preview.")

        if preview.get("submitted") is not False:
            raise ValueError("Request has already been processed.")

        data = {
            "department": department,
            "title": preview["title"],
            "purpose": preview["purpose"],
            "quantity": preview["quantity"],
            "specifications": preview.get("specifications", ""),
            "needed_by": preview.get("needed_by"),
        }

        return DemandService.save(
            user,
            data,
            submit=False,
            operation_key=operation_key,
        )
