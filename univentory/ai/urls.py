
from django.urls import path
from . import views

app_name = "ai"

urlpatterns = [
    path("monitoring/", views.monitoring_dashboard, name="monitoring"),
]
