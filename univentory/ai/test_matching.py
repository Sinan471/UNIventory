from django.test import TestCase
from unittest.mock import patch, MagicMock

from ai.matching import MatchingService


class MatchingServiceTest(TestCase):

    @patch("ai.matching.CatalogueQueryService.search")
    def test_get_candidates_returns_top_five(self, mock_search):

        user = MagicMock()

        mock_listings = []

        for i in range(7):
            listing = MagicMock()
            listing.pk = i + 1
            listing.asset_id = i + 10
            listing.title = f"Listing {i + 1}"
            listing.public_description = "Available asset"
            listing.asset.category.name = "Furniture"
            listing.department = "IT"
            listing.free_qty = 5

            mock_listings.append(listing)

        mock_search.return_value = mock_listings

        results = MatchingService.get_candidates(
            user,
            needed_category_id=1,
            required_quantity=2
        )

        self.assertEqual(len(results), 5)
        self.assertEqual(results[0]["title"], "Listing 1")

    @patch("ai.matching.CatalogueQueryService.search")
    def test_invalid_quantity(self, mock_search):

        with self.assertRaises(ValueError):
            MatchingService.get_candidates(
                MagicMock(),
                needed_category_id=1,
                required_quantity=0
            )

        mock_search.assert_not_called()