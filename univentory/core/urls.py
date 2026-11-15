from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("design/", views.design_reference, name="design_reference"),
    path("healthz/", views.healthz, name="healthz"),
]
