from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.index, name="index"),
    path("<int:pk>/open/", views.open_item, name="open"),
    path("read-all/", views.mark_all_read, name="read_all"),
]
