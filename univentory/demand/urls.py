from django.urls import path
from . import views

app_name = "demand"
urlpatterns = [
    path("", views.request_list, name="list"),
    path("new/", views.request_form, name="new"),
    path("from-listing/<int:listing_id>/", views.request_form, name="new_from_listing"),
    path("<int:pk>/", views.request_detail, name="detail"),
    path("<int:pk>/edit/", views.request_form, name="edit"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
]
