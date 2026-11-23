from django.urls import path

from . import views

app_name = "signatures"

urlpatterns = [
    path("me/", views.my_signature, name="my_signature"),
    path("me/image.png", views.my_signature_image, name="my_signature_image"),
    path("files/<uuid:attachment_id>/final/", views.final_copy, name="final_copy"),
    path("test-ca.crt", views.test_ca, name="test_ca"),
]
