from django.urls import path
from . import views

app_name = "workflow"
urlpatterns = [path("", views.queue, name="queue"), path("request/<int:pk>/", views.review, name="review"),
               path("release/<int:pk>/", views.release_review, name="release_review")]
