from identity.models import Role, UserRole
from django.db.models import Q
from .models import Notification


class NotificationService:
    @staticmethod
    def notify(user, message):
        if user.is_active:
            return Notification.objects.create(recipient=user, message=message)

    @staticmethod
    def department_representatives(department, message, exclude_user=None):
        recipients = UserRole.objects.active().filter(role__code=Role.DEPT_REP, user__is_active=True).filter(
            Q(department=department) | Q(department__isnull=True)).exclude(user=exclude_user).values_list("user_id", flat=True).distinct()
        Notification.objects.bulk_create([Notification(recipient_id=uid, message=message) for uid in recipients])
