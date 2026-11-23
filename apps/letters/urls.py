from django.urls import path

from . import views

app_name = "letters"

urlpatterns = [
    path("new/", views.create, name="create"),
    path("<uuid:pk>/revise/", views.revise, name="revise"),
    path("<uuid:pk>/issue/", views.issue, name="issue"),
    path("<uuid:pk>/word/", views.download_docx, name="docx"),
    path("letterhead/", views.letterhead, name="letterhead"),
    path("letterhead/emblem.png", views.emblem_image, name="emblem"),
]
