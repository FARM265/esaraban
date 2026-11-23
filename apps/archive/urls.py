from django.urls import path

from . import views

app_name = "archive"

urlpatterns = [
    path("", views.index, name="index"),
    path("documents/<uuid:pk>/archive/", views.archive, name="archive"),
    path("documents/<uuid:pk>/release/", views.release, name="release"),
]
