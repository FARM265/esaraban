from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("system/status/", views.status, name="status"),
    path("healthz", views.healthz, name="healthz"),
]
