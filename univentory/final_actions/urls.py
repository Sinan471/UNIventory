from django.urls import path
from . import views
app_name = "final_actions"
urlpatterns = [path("", views.action_list, name="list"), path("propose/<int:pk>/", views.propose, name="propose"), path("<int:pk>/", views.detail, name="detail")]
