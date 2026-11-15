from django.urls import path

from catalogue import views

app_name = "catalogue"

urlpatterns = [
    path("", views.exchange, name="exchange"),
    path("listings/<int:pk>/", views.listing_detail, name="listing_detail"),
    path("listings/<int:pk>/edit/", views.listing_edit, name="listing_edit"),
    path("listings/<int:pk>/<str:action>/", views.listing_action, name="listing_action"),
    path("assets/<int:asset_id>/list/", views.listing_new, name="listing_new"),
    path("release-reviews/", views.release_queue, name="release_queue"),
    path("release-reviews/<int:pk>/decide/", views.release_decide, name="release_decide"),
]
