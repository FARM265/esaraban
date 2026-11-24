from django.urls import path, re_path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("system/status/", views.status, name="status"),
    path("healthz", views.healthz, name="healthz"),
    re_path(r"^(?P<name>google[0-9a-f]{8,32}\.html)$", views.google_verification, name="google_verification"),
]
