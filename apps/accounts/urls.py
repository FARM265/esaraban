from django.urls import path

from . import views_auth as auth
from . import views_manage as manage

app_name = "accounts"

urlpatterns = [
    # เข้าสู่ระบบ
    path("login/", auth.login_view, name="login"),
    path("login/verify/", auth.mfa_verify, name="mfa_verify"),
    path("login/setup-mfa/", auth.mfa_setup, name="mfa_setup"),
    path("logout/", auth.logout_view, name="logout"),
    # บัญชีของฉัน
    path("me/", manage.profile, name="profile"),
    path("me/password/", auth.password_change, name="password_change"),
    path("me/backup-codes/", auth.backup_codes, name="backup_codes"),
    path("me/backup-codes/regenerate/", auth.regenerate_backup_codes, name="regenerate_backup_codes"),
    # จัดการผู้ใช้
    path("users/", manage.user_list, name="user_list"),
    path("users/new/", manage.user_create, name="user_create"),
    path("users/<uuid:pk>/", manage.user_detail, name="user_detail"),
    path("users/<uuid:pk>/roles/add/", manage.user_role_add, name="user_role_add"),
    path("users/<uuid:pk>/roles/<int:assignment_id>/remove/", manage.user_role_remove, name="user_role_remove"),
    path("users/<uuid:pk>/password/", manage.user_set_password, name="user_set_password"),
    path("users/<uuid:pk>/reset-mfa/", manage.user_reset_mfa, name="user_reset_mfa"),
    path("users/<uuid:pk>/toggle-active/", manage.user_toggle_active, name="user_toggle_active"),
    path("users/<uuid:pk>/delete/", manage.user_delete, name="user_delete"),
    # กลุ่มงาน
    path("departments/", manage.department_list, name="department_list"),
    path("departments/new/", manage.department_edit, name="department_create"),
    path("departments/<int:pk>/", manage.department_edit, name="department_edit"),
]
