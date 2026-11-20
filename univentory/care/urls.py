from django.urls import path
from . import views
app_name = "care"
urlpatterns = [path("", views.care_list, name="list"), path("report/<int:pk>/", views.report, name="report"),
               path("inspect/<int:pk>/", views.inspect, name="inspect"), path("case/<int:pk>/", views.case_detail, name="case")]
