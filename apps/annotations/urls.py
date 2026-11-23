from django.urls import path

from . import views

app_name = "annotations"

urlpatterns = [
    path("files/<uuid:attachment_id>/", views.annotation_list, name="list"),
    path("<int:pk>/delete/", views.annotation_delete, name="delete"),
    path("<int:pk>/move/", views.annotation_move, name="move"),
]
