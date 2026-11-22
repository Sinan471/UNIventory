from django.urls import path
from . import views
app_name = "notifications"
urlpatterns = [path("", views.list_notifications, name="list"), path("<int:pk>/read/", views.mark_read, name="read"),
               path("read-all/", views.mark_all_read, name="read_all")]
