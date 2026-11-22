from django.urls import path

from . import views

app_name = "sustainability"

urlpatterns = [path("", views.impact, name="impact")]
