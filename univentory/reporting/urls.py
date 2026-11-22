from django.urls import path

from . import views

app_name = "reporting"

urlpatterns = [
    path("", views.index, name="index"),
    path("export.csv", views.export, name="export"),
    path("snapshots/new/", views.snapshot_create, name="snapshot_create"),
    path("snapshots/<int:pk>/", views.snapshot_detail, name="snapshot"),
    path("export/<int:snapshot_id>/", views.export_report_csv, name="export_csv"),
]
