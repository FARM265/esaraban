from django.urls import path

from . import views

app_name = "workflow"

urlpatterns = [
    path("tasks/", views.my_tasks, name="my_tasks"),
    path("start/<uuid:document_id>/", views.start, name="start"),
    path("tasks/<uuid:task_id>/act/", views.act, name="act"),
    path("templates/", views.template_list, name="template_list"),
    path("templates/new/", views.template_edit, name="template_create"),
    path("templates/<int:pk>/", views.template_edit, name="template_edit"),
    path("delegations/", views.delegations, name="delegations"),
    path("delegations/<int:pk>/revoke/", views.delegation_revoke, name="delegation_revoke"),
]
