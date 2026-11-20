from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from core.web import active_role_required
from .models import Notification


@active_role_required
def list_notifications(request):
    return render(request, "notifications/list.html", {"items": Notification.objects.filter(recipient=request.user)})


@require_POST
@active_role_required
def mark_read(request, pk):
    row = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if row.read_at is None:
        row.read_at = timezone.now()
        row.save(update_fields=["read_at"])
    return redirect("notifications:list")
