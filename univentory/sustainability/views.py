"""Impact dashboard (C7, FR-50, SUS-01 to SUS-10). Owner: Jessica.

Every figure comes from ImpactCalculator over recorded evidence. Each
measure shows its formula, inputs, unit, status and calculation version;
missing evidence is shown as Unknown and a zero denominator as Not applicable.
"""
from django.shortcuts import render

from core.web import active_role_required, permission_denied_response

from .apps import can_view_impact
from .services import ImpactCalculator


@active_role_required
def impact(request):
    if not can_view_impact(request.user):
        return permission_denied_response(request, "Impact indicators are available to oversight roles and department representatives.")
    data = ImpactCalculator.calculate_all()
    savings = data["financial_savings"]
    repair = data["repair_outcomes"]
    diversion = data["waste_diversion"]
    life = data["life_extension"]
    carbon = data["carbon_reduction"]
    avoided = data["avoided_purchases"]
    rows = [
        {"name": "Reused units", "value": data["reused_units"]["value"], "unit": "units", "status": "Observed",
         "formula": "Sum of units accepted by the assigned receiver", "inputs": "Receipt records",
         "note": "Holds and dispatches do not count; only accepted receipts."},
        {"name": "Avoided purchases", "value": avoided["baseline_value_aed"], "unit": "AED", "aed": True,
         "status": f"{avoided['count']} procurement-validated", "formula": "Sum of baseline value of validated avoided purchases",
         "inputs": "Avoided-purchase records with procurement validation", "note": "A catalogue value alone never counts."},
        {"name": "Net financial savings", "value": savings["financial_savings_aed"], "unit": "AED", "aed": True,
         "status": "Calculated", "formula": "Validated avoided purchases minus transfer, repair and refurbishment costs",
         "inputs": f"Avoided AED {savings['avoided_purchase_value_aed']:,.2f}; attributable costs AED {savings['attributable_costs_aed']:,.2f}",
         "note": "Negative savings are shown as negative."},
        {"name": "Waste diversion", "value": diversion["value"], "unit": "%", "status": diversion["status"].replace("_", " ").capitalize(),
         "formula": "Units with a completed qualifying outcome / all units entering the unwanted cohort x 100",
         "inputs": f"{diversion['numerator']} diverted of {diversion['denominator']} in cohort",
         "note": "Pending outcomes stay in the denominator."},
        {"name": "Repair success rate", "value": repair["value"], "unit": "%", "status": repair["status"].replace("_", " ").capitalize(),
         "formula": "Successful closed repair jobs / all closed repair jobs x 100",
         "inputs": f"{repair['successful_jobs']} successful of {repair['closed_jobs']} closed",
         "note": "Inspection-only (no repair needed) and open jobs are excluded."},
        {"name": "Asset life extension", "value": life["value"], "unit": "days per asset", "status": life["status"].capitalize(),
         "formula": "Average of revised retirement date minus baseline retirement date, verified continued use only",
         "inputs": f"{life['verified_assets']} verified asset(s)", "note": "Estimated future months are not counted as observed."},
        {"name": "Estimated carbon reduction", "value": carbon["value"], "unit": "kg CO2e",
         "status": carbon["status"].replace("_", " ").capitalize(),
         "formula": "Accepted units x (replacement factor - transfer factor)",
         "inputs": ", ".join(carbon.get("sources", [])) or "No factors recorded", "note": carbon.get("note", "")},
    ]
    from django.db.models import Sum

    from core import charts
    from exchange.models import ReceiptEvent

    from .models import AvoidedPurchase, CohortOutcome, UnwantedCohort

    months, received = charts.count_by_month(ReceiptEvent.objects.all(), "created_at", sum_field="quantity")
    _, avoided_m = charts.count_by_month(AvoidedPurchase.objects.filter(is_procurement_validated=True),
                                         "recorded_at", sum_field="baseline_value_aed")
    outcome = {o: CohortOutcome.objects.filter(outcome__in=keys).aggregate(t=Sum("quantity"))["t"] or 0
               for o, keys in (("Reused or repaired", ["REUSE", "REPAIR_TO_USE", "REFURBISHMENT"]),
                               ("Donated", ["DONATION"]), ("Recycled", ["RECYCLING"]))}
    cohort_total = UnwantedCohort.objects.aggregate(t=Sum("quantity"))["t"] or 0
    settled = CohortOutcome.objects.aggregate(t=Sum("quantity"))["t"] or 0
    outcome["Still pending"] = max(cohort_total - settled, 0)
    seg = list(outcome.items())
    diversion_pct = diversion["value"]
    sav = [("Validated avoided purchases", savings["avoided_purchase_value_aed"]),
           ("Transfer and repair costs", savings["attributable_costs_aed"]),
           ("Net savings", savings["financial_savings_aed"])]
    peak = max([float(v) for _, v in sav], default=1) or 1
    repair_seg = [("Successful", repair["successful_jobs"]), ("Failed", repair["closed_jobs"] - repair["successful_jobs"])]
    return render(request, "sustainability/impact.html", {
        "rows": rows, "version": data["calculation_version"], "nav_current": "impact",
        "reused": charts.fmt(data["reused_units"]["value"]), "reused_spark": charts.sparkline(received),
        "avoided": charts.fmt(avoided["baseline_value_aed"]), "avoided_spark": charts.sparkline(avoided_m),
        "net": charts.fmt(savings["financial_savings_aed"]),
        "carbon": charts.fmt(carbon["value"]) if carbon["value"] is not None else None, "carbon_status": rows[6]["status"],
        "trend": charts.area_chart(months, received, unit="units"),
        "trend_table": charts.table(["Month", "Units accepted"], list(zip(months, received))),
        "outcome_donut": charts.donut(seg, center_value=(f"{diversion_pct:.0f}%" if diversion_pct is not None else "n/a"),
                                      center_label="diverted"),
        "outcome_legend": charts.legend([n for n, _ in seg], [v for _, v in seg], "units"),
        "outcome_table": charts.table(["Outcome", "Units"], seg),
        "savings": [{"name": n, "value": charts.fmt(v), "pct": max(2, round(100 * float(v) / peak)) if float(v) > 0 else 0,
                     "tone": i + 1} for i, (n, v) in enumerate(sav)],
        "repair_donut": charts.donut(repair_seg, center_value=(f"{repair['value']:.0f}%" if repair["value"] is not None else "n/a"),
                                     center_label="success"),
        "repair_legend": charts.legend([n for n, _ in repair_seg], [v for _, v in repair_seg]),
        "life": life,
    })
