from django.urls import path

from inventory import views

app_name = "inventory"

urlpatterns = [
    path("", views.my_assets, name="my_assets"),
    path("new/", views.asset_new, name="asset_new"),
    path("<int:pk>/", views.asset_detail, name="asset_detail"),
    path("<int:pk>/edit/", views.asset_edit, name="asset_edit"),
    path("<int:pk>/activate/", views.asset_activate, name="asset_activate"),
    path("<int:pk>/evidence/", views.attachment_upload, name="attachment_upload"),
    path("portions/<int:pk>/split/", views.portion_split, name="portion_split"),
    path("portions/<int:pk>/adjust/", views.portion_adjust, name="portion_adjust"),
    path("portions/<int:pk>/state/", views.portion_state, name="portion_state"),
    path("evidence/<int:pk>/", views.attachment_download, name="attachment_download"),
    path("evidence/<int:pk>/withdraw/", views.attachment_withdraw, name="attachment_withdraw"),
]
