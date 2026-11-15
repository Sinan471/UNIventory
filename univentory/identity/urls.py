from django.urls import path

from identity import views

app_name = "identity"

urlpatterns = [
    path("sign-in/", views.login_page, name="login"),
    path("sign-in/start/", views.sso_start, name="sso_start"),
    path("sign-in/callback/", views.sso_callback, name="sso_callback"),
    path("sign-in/dev/", views.dev_login, name="dev_login"),
    path("sign-out/", views.logout_view, name="logout"),
    path("signed-out/", views.signed_out, name="signed_out"),
    path("admin/", views.admin_home, name="admin_home"),
    path("admin/people/", views.people, name="people"),
    path("admin/people/<int:pk>/", views.person_detail, name="person_detail"),
    path("admin/people/<int:pk>/status/", views.account_status, name="account_status"),
    path("admin/grants/<int:pk>/revoke/", views.revoke_grant, name="revoke_grant"),
    path("admin/<str:kind>/", views.reference_list, name="reference_list"),
    path("admin/<str:kind>/new/", views.reference_edit, name="reference_new"),
    path("admin/<str:kind>/<int:pk>/", views.reference_edit, name="reference_edit"),
    path("admin/<str:kind>/<int:pk>/active/", views.reference_toggle, name="reference_toggle"),
]
