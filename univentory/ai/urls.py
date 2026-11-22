from django.urls import path

from . import views

app_name = "ai"

urlpatterns = [
    path("monitoring/", views.monitoring_dashboard, name="monitoring"),
    path("assistant/", views.assistant, name="assistant"),
    path("assistant/confirm/", views.assistant_confirm, name="assistant_confirm"),
    path("classify/", views.classify, name="classify"),
    path("matches/<int:request_id>/decide/", views.match_decide, name="match_decide"),
]
