from django.urls import path

from . import views

app_name = "registry"

urlpatterns = [
    path("", views.index, name="index"),
    path("books/<int:book_id>/issue/", views.issue, name="issue"),
    path("numbers/<int:number_id>/void/", views.void, name="void"),
    path("books/new/", views.book_edit, name="book_create"),
    path("books/<int:pk>/", views.book_edit, name="book_edit"),
]
