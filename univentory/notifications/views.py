from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from core.web import active_role_required
from .models import Notification


@active_role_required
def list_notifications(request):
    """FR-53: per-user read state with an unread filter."""
    mine = Notification.objects.filter(recipient=request.user)
    unread_only = request.GET.get("filter") == "unread"
    items = mine.filter(read_at__isnull=True) if unread_only else mine
    return render(request, "notifications/list.html", {
        "items": items[:200], "unread_only": unread_only,
        "unread_count": mine.filter(read_at__isnull=True).count(), "nav_current": "notifications",
    })


@require_POST
@active_role_required
def mark_read(request, pk):
    row = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if row.read_at is None:
        row.read_at = timezone.now()
        row.save(update_fields=["read_at"])
    return redirect("notifications:list")


@require_POST
@active_role_required
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect("notifications:list")
