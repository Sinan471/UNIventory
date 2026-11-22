
from django.urls import path
from . import views

app_name = "reporting"

urlpatterns = [
    path(
        "export/<int:snapshot_id>/",
        views.export_report_csv,
        name="export_csv",
    ),
]

