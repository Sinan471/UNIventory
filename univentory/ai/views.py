"""AI feature screens (owner: Jessica's ai module).

No live model is configured in this release, so every feature here runs on
the deterministic, rule-based fallback and says so on screen (AI-18). The
controls the documents require still apply: scoped retrieval, explicit
human confirmation, provenance records and no stock or approval changes.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.contracts import DomainError
from core.web import active_role_required, permission_denied_response
from identity.models import Category, Department, Role
from identity.policy import AccessPolicy

from .assistant import AssistantService
from .models import AIRun, MatchRecommendation, RecommendationReview
from .monitoring import AIMonitoringService

RULES_VERSION = "rules-1.0"


def _record_run(user, task, result: dict, status=AIRun.Status.COMPLETED):
    """Provenance without the private prompt body (AI-14, FR-56)."""
    now = timezone.now()
    return AIRun.objects.create(user=user, task_type=task, status=status, prompt_version=RULES_VERSION,
                                schema_version="1.0", result=result, started_at=now, completed_at=now,
                                correlation_id=uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# Monitoring (oversight roles only)
# ---------------------------------------------------------------------------
MONITOR_ROLES = {Role.SYSADMIN, Role.SUSTAINABILITY, Role.MANAGEMENT, Role.AUDITOR}


def can_monitor(user) -> bool:
    return bool(AccessPolicy.role_codes(user) & MONITOR_ROLES)


@active_role_required
def monitoring_dashboard(request):
    if not can_monitor(request.user):
        return permission_denied_response(request, "AI monitoring is limited to oversight roles.")
    summary = AIMonitoringService.get_summary()
    return render(request, "ai/monitoring.html", {"summary": summary, "nav_current": "impact"})


# ---------------------------------------------------------------------------
# Match review (AI-04, AI-16, AI-17)
# ---------------------------------------------------------------------------
@require_POST
@active_role_required
def match_decide(request, request_id):
    from demand.models import ResourceRequest

    from .matching import MatchingService

    need = get_object_or_404(ResourceRequest, pk=request_id, requester=request.user,
                             department_id__in=AccessPolicy.departments_with_role(request.user, Role.REQUESTER))
    decision = request.POST.get("decision", "")
    if decision not in (RecommendationReview.Decision.ACCEPTED, RecommendationReview.Decision.REJECTED):
        return permission_denied_response(request, "Choose a valid decision.")
    try:
        listing_id = int(request.POST.get("listing", ""))
    except ValueError:
        return redirect("demand:detail", pk=need.pk)
    # Recheck against current stock, access and versions before acting (AI-17).
    current = {m["listing_id"]: m for m in MatchingService.for_request(request.user, need)}
    match = current.get(listing_id)
    if match is None:
        messages.warning(request, "That suggestion is out of date: the item is no longer available to you. "
                                  "The list below has been refreshed.")
        return redirect("demand:detail", pk=need.pk)
    rec = MatchRecommendation.objects.create(
        request=need, listing_id=listing_id, score=Decimal(str(match["score"])), factors=match["factors"],
        reasons=match["reasons"], missing_evidence=match["missing_evidence"], ranking_version=match["ranking_version"],
        source_revisions={"request_version": need.version})
    RecommendationReview.objects.create(recommendation=rec, reviewer=request.user, decision=decision,
                                        reason=request.POST.get("reason", "")[:500])
    _record_run(request.user, AIRun.TaskType.MATCHING,
                {"request": need.pk, "listing": listing_id, "decision": decision, "score": str(match["score"])})
    if decision == RecommendationReview.Decision.REJECTED:
        messages.info(request, "Recorded that this suggestion is not suitable.")
        return redirect("demand:detail", pk=need.pk)
    if need.state not in (ResourceRequest.State.APPROVED, ResourceRequest.State.PARTIAL):
        messages.info(request, "Suggestion recorded. You can reserve it after your need is approved.")
        return redirect("demand:detail", pk=need.pk)
    return redirect(reverse("transfer:reserve", args=[need.pk]) + f"?listing={listing_id}")


# ---------------------------------------------------------------------------
# Classification suggestion (AI-01, AI-02)
# ---------------------------------------------------------------------------
VOCAB = {
    "IT": "laptop desktop computer pc monitor screen printer keyboard mouse server tablet notebook thinkpad dell hp lenovo",
    "FURN": "chair chairs desk desks table cabinet shelf sofa stool furniture seat seating drawer filing",
    "LAB": "microscope centrifuge balance hotplate stirrer pipette beaker oven incubator fume spectrometer lab laboratory",
    "AV": "projector display speaker camera microphone screen tv audio video conference speakerphone",
    "OFF": "paper binder binders whiteboard stationery pens folders stapler toner envelopes organiser",
    "TOOL": "drill saw hammer wrench workbench caliper tool tools goggles safety screwdriver grinder",
}


@require_POST
@active_role_required
def classify(request):
    if not AccessPolicy.departments_with_role(request.user, Role.CUSTODIAN):
        return JsonResponse({"status": "DENIED"}, status=403)
    text = f"{request.POST.get('title', '')} {request.POST.get('description', '')}"[:2000].lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    if not words:
        return JsonResponse({"status": "INSUFFICIENT_EVIDENCE", "message": "Enter a title or description first."})
    best = None
    for category in Category.objects.active():
        vocab = set(VOCAB.get(category.code, "").split()) | set(re.findall(r"[a-z0-9]+", category.name.lower()))
        for sub in category.subcategories or []:
            vocab |= set(re.findall(r"[a-z0-9]+", str(sub).lower()))
        hits = sorted(words & vocab)
        if hits and (best is None or len(hits) > len(best[1])):
            best = (category, hits)
    missing = [label for key, label in (("description", "description"),) if not request.POST.get(key, "").strip()]
    if best is None:
        _record_run(request.user, AIRun.TaskType.CLASSIFICATION, {"status": "NO_MATCH"})
        return JsonResponse({"status": "INSUFFICIENT_EVIDENCE",
                             "message": "No category could be suggested from this text. Choose one manually."})
    category, hits = best
    status = "SUFFICIENT_EVIDENCE" if len(hits) >= 2 else "NEEDS_REVIEW"
    _record_run(request.user, AIRun.TaskType.CLASSIFICATION, {"category": category.pk, "evidence": hits})
    return JsonResponse({
        "status": status, "category_id": category.pk, "category_name": category.name,
        "evidence": hits, "missing": missing,
        "message": "Suggestion only. Review it; nothing is saved until you save the asset. "
                   "Condition and safety are never inferred from text.",
    })


# ---------------------------------------------------------------------------
# Campus assistant (AI-11 to AI-13)
# ---------------------------------------------------------------------------
GUIDANCE = [
    (("hold", "48", "expire", "reservation"), "Reservations and holds",
     "A reservation holds nothing until the owning department representative approves it. An approved hold lasts "
     "48 hours; the receiving department must approve the transfer in that time or the units return to free stock.",
     "UNIventory requirements FR-21 to FR-25"),
    (("approve", "approval", "who", "independent", "self"), "Who approves what",
     "Your own department representative approves your need. The owning department approves the hold, and the "
     "receiving department approves the transfer. Nobody can approve their own request, and administrators have "
     "no business approval power.", "Business rules BR-01, BR-02"),
    (("receive", "receipt", "deliver", "delivery", "partial"), "Receiving items",
     "Only the assigned receiver confirms what physically arrived. Partial deliveries are recorded once; only "
     "accepted units count towards a request.", "FR-33, FR-34, BR-07"),
    (("repair", "defect", "broken", "maintenance", "fault"), "Reporting a fault",
     "The custodian reports a defect from Care. The affected units are blocked at once until maintenance staff "
     "inspect them; repaired items return to use only after an independent verification.", "FR-37 to FR-41"),
    (("donate", "recycle", "dispose", "disposal", "donation"), "Donation, recycling and disposal",
     "The custodian proposes the outcome, a department representative approves it, and the outcome only counts "
     "once the custodian records completion evidence such as a receipt or certificate.", "FR-43 to FR-45"),
]
STOP = set("a an the i we need want looking for some to of and or in on at my our please can you find show me is are "
           "do does have any with get new".split())


def _quantity(text):
    match = re.search(r"\b(\d{1,4})\b", text)
    return Decimal(match.group(1)) if match else Decimal(1)


def _answer(user, text):
    lower = text.lower()
    words = [w for w in re.findall(r"[a-z0-9]+", lower) if w not in STOP and not w.isdigit()]
    answer = {"text": "", "links": [], "preview": None, "source": ""}
    if re.search(r"\b(status|my requests|track|where is)\b", lower):
        from demand.models import ResourceRequest

        rows = ResourceRequest.objects.filter(requester=user)[:6]
        if not rows:
            answer["text"] = "You have no requests yet."
        else:
            answer["text"] = "Here are your latest requests and their current status."
            answer["links"] = [{"label": f"{r.title}: {r.get_state_display()}", "url": reverse("demand:detail", args=[r.pk])}
                               for r in rows]
        answer["source"] = "Your request records"
        return answer
    for keys, title, body, source in GUIDANCE:
        if any(k in lower for k in keys) and re.search(r"\b(how|what|who|when|why|policy|rule)\b", lower):
            answer.update(text=f"{title}. {body}", source=f"Approved guidance: {source}")
            return answer
    if not words:
        answer["text"] = "Tell me what you are looking for, for example 'we need 4 office chairs'."
        return answer
    results = AssistantService.search_catalogue(user, " ".join(words[:3]))
    if not results and len(words) > 1:
        for word in words:
            results = AssistantService.search_catalogue(user, word.rstrip("s"))
            if results:
                break
    if results:
        answer["text"] = "These released items match. Open one to check its condition and location."
        answer["links"] = [{"label": f"{r['title']} ({r['available_quantity'].rstrip('0').rstrip('.')} free, {r['category']})",
                            "url": reverse("catalogue:listing_detail", args=[r["listing_id"]])} for r in results]
        answer["source"] = "Exchange listings you are allowed to see"
    else:
        answer["text"] = ("I could not find a released item for that, and I will not guess. "
                          "You can record a need so your department can find or buy it.")
    if re.search(r"\b(need|needs|want|request|looking)\b", lower) and AccessPolicy.departments_with_role(user, Role.REQUESTER):
        answer["preview"] = {"title": text.strip()[:120].capitalize(), "purpose": text.strip()[:500],
                             "quantity": str(_quantity(lower))}
    return answer


@active_role_required
def assistant(request):
    history = request.session.get("assistant_history", [])
    if request.method == "POST" and request.POST.get("action") == "ask":
        text = (request.POST.get("message") or "").strip()[:500]
        if text:
            reply = _answer(request.user, text)
            history = (history + [{"role": "user", "text": text}, {"role": "bot", **reply}])[-12:]
            request.session["assistant_history"] = history
            _record_run(request.user, AIRun.TaskType.ASSISTANT,
                        {"links": [link["url"] for link in reply["links"]], "preview": bool(reply["preview"])})
        return redirect("ai:assistant")
    if request.method == "POST" and request.POST.get("action") == "clear":
        request.session["assistant_history"] = []
        return redirect("ai:assistant")
    departments = Department.objects.filter(pk__in=AccessPolicy.departments_with_role(request.user, Role.REQUESTER))
    return render(request, "ai/assistant.html", {"history": history, "departments": departments,
                                                 "operation_key": uuid.uuid4().hex, "nav_current": "assistant"})


@require_POST
@active_role_required
def assistant_confirm(request):
    """Create a DRAFT request from a reviewed preview after explicit confirmation (AI-12)."""
    if request.POST.get("confirmed") != "yes":
        messages.error(request, "Tick the confirmation box to create the draft.")
        return redirect("ai:assistant")
    try:
        department = Department.objects.get(pk=int(request.POST.get("department", "")),
                                            pk__in=AccessPolicy.departments_with_role(request.user, Role.REQUESTER))
        preview = AssistantService.create_request_preview(request.POST.get("title", ""), request.POST.get("purpose", ""),
                                                          request.POST.get("quantity", ""))
        item = AssistantService.confirm_request(request.user, preview, department, confirmed=True,
                                                operation_key=(request.POST.get("operation_key") or "")[:64])
    except (Department.DoesNotExist, ValueError, InvalidOperation) as exc:
        messages.error(request, f"The draft was not created: {exc}" if str(exc) else "The draft was not created.")
        return redirect("ai:assistant")
    except DomainError as exc:
        messages.error(request, exc.message)
        return redirect("ai:assistant")
    messages.success(request, "Draft request created. Check it and submit it for approval when ready.")
    return redirect("demand:detail", pk=item.pk)
