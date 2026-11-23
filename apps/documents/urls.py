from django.urls import path

from . import calendar_views, views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="list"),
    path("receive/", views.receive, name="receive"),
    path("<uuid:pk>/", views.document_detail, name="detail"),
    path("<uuid:pk>/edit/", views.document_edit, name="edit"),
    path("<uuid:pk>/calendar/", calendar_views.calendar_from_document, name="calendar"),
    path("calendar/", calendar_views.calendar_upload, name="calendar_upload"),
    path("files/<uuid:pk>/", views.attachment_file, name="file"),
    path("files/<uuid:pk>/view/", views.attachment_viewer, name="viewer"),
]
