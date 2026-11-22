"""Checks for the demo-readiness and hardening pass (owner: Jesher).

Covers cross-module behaviour added in this pass: scoped reports and CSV
injection, AI monitoring access, request validation (FR-15), match ordering,
narrative number checks, security headers and workbench scoping.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.csvsafe import safe_cell
from core.testing import World, user
from core.contracts import ValidationFailed
from demand.services import DemandService
from identity.models import Role
from identity.tests import sign_in


class CsvSafetyTests(TestCase):
    def test_formula_cells_are_neutralised(self):
        for value in ["=1+1", "+SUM(A1)", "-2+3", "@cmd", "\tTAB", " =HYPERLINK()"]:
            self.assertTrue(safe_cell(value).startswith("'"), value)
        self.assertEqual(safe_cell("Chairs"), "Chairs")
        self.assertEqual(safe_cell("كرسي"), "كرسي")
        self.assertEqual(safe_cell(None), "")


class ReportScopeTests(TestCase):
    def setUp(self):
        self.w = World()
        self.sustain = user("sustain", (Role.SUSTAINABILITY, None))
        self.data = {"department": self.w.other, "title": "=HYPERLINK(\"http://evil\")", "purpose": "Room",
                     "specifications": "", "quantity": Decimal("2"), "needed_by": None, "urgent": False,
                     "urgent_reason": ""}

    def test_requester_cannot_open_reports(self):
        client = Client()
        sign_in(client, self.w.requester)
        self.assertEqual(client.get("/reporting/").status_code, 403)
        self.assertEqual(client.get("/reporting/export.csv").status_code, 403)

    def test_rep_export_is_scoped_and_neutralised(self):
        DemandService.save(self.w.requester, self.data, submit=True)
        client = Client()
        sign_in(client, self.w.rep)  # rep of ENG, request belongs to SCI
        body = client.get("/reporting/export.csv").content.decode("utf-8-sig")
        self.assertNotIn("HYPERLINK", body)
        # A department outside the rep's scope in the query string is ignored, never widened.
        body = client.get(f"/reporting/export.csv?department={self.w.other.pk}").content.decode("utf-8-sig")
        self.assertNotIn("HYPERLINK", body)
        sign_in(client, self.sustain)
        body = client.get("/reporting/export.csv").content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", body)


class MonitoringAccessTests(TestCase):
    def test_monitoring_limited_to_oversight_roles(self):
        w = World()
        client = Client()
        sign_in(client, w.requester)
        self.assertEqual(client.get("/ai/monitoring/").status_code, 403)
        sign_in(client, user("aud", (Role.AUDITOR, None)))
        self.assertEqual(client.get("/ai/monitoring/").status_code, 200)


class RequestValidationTests(TestCase):
    def test_required_date_in_the_past_is_rejected(self):
        w = World()
        data = {"department": w.other, "title": "Chairs", "purpose": "Room", "specifications": "",
                "quantity": Decimal("2"), "needed_by": timezone.localdate() - timedelta(days=1),
                "urgent": False, "urgent_reason": ""}
        with self.assertRaises(ValidationFailed):
            DemandService.save(w.requester, data, submit=True)

    def test_destination_must_belong_to_department(self):
        w = World()
        data = {"department": w.other, "title": "Chairs", "purpose": "Room", "specifications": "",
                "quantity": Decimal("2"), "needed_by": None, "urgent": False, "urgent_reason": "",
                "destination": w.loc}
        with self.assertRaises(ValidationFailed):
            DemandService.save(w.requester, data)

    def test_form_requires_category_date_and_destination_to_submit(self):
        w = World()
        client = Client()
        sign_in(client, w.requester)
        response = client.post("/demand/new/", {"department": w.other.pk, "title": "Chairs", "purpose": "Teaching",
                                                "quantity": "2", "action": "submit", "operation_key": "k-1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose a category to submit.")
        self.assertContains(response, "Choose where the items should go.")


class MatchOrderingTests(TestCase):
    def test_highest_score_first(self):
        from unittest.mock import MagicMock, patch

        from ai.matching import MatchingService

        listings = []
        for pk, free in [(1, 1), (2, 5)]:
            listing = MagicMock(pk=pk, asset_id=pk, title=f"L{pk}", public_description="", free_qty=free)
            listing.asset.category.name = "Furniture"
            listings.append(listing)
        with patch("ai.matching.CatalogueQueryService.search", return_value=listings):
            results = MatchingService.get_candidates(MagicMock(), needed_category_id=1, required_quantity=1)
        self.assertGreaterEqual(results[0]["score"], results[-1]["score"])


class NarrativeCheckTests(TestCase):
    def test_numbers_must_match_snapshot(self):
        from reporting.views import unsupported_numbers

        data = {"requests": 8, "accepted_units": "10", "savings_aed": "8570.00"}
        self.assertEqual(unsupported_numbers("8 requests, 10 units, AED 8,570.00", data), [])
        self.assertEqual(unsupported_numbers("12 requests were met", data), ["12"])


class HeaderTests(TestCase):
    def test_security_headers_present(self):
        response = Client().get("/identity/sign-in/")
        csp = response["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")


class WorkbenchScopeTests(TestCase):
    def test_own_request_never_counts_as_waiting_for_its_author(self):
        from core.workbench import tasks_for

        w = World()
        both = user("both", (Role.REQUESTER, w.other), (Role.DEPT_REP, w.other))
        DemandService.save(both, {"department": w.other, "title": "Chairs", "purpose": "Room", "specifications": "",
                                  "quantity": Decimal("1"), "needed_by": None, "urgent": False, "urgent_reason": ""},
                           submit=True)
        needs = next(t for t in tasks_for(both) if t.key == "needs")
        self.assertEqual(needs.count, 0)

    def test_no_role_sees_no_tasks(self):
        from core.workbench import tasks_for

        self.assertEqual(tasks_for(World().norole), [])
