from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.index, name="index"),
    path("verify/", views.verify, name="verify"),
    path("export.xlsx", views.export, name="export"),
]
