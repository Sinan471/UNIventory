from django.urls import path
from . import views

app_name = "transfer"
urlpatterns = [path("", views.queue, name="queue"), path("request/<int:pk>/", views.reserve, name="reserve"),
    path("reservation/<int:pk>/", views.detail, name="detail"), path("receipt/<int:pk>/", views.receipt, name="receipt"),
    path("resolution/<int:pk>/", views.resolve, name="resolve")]
