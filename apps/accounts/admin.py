"""
Django admin สำหรับ superuser ใช้ตรวจข้อมูลเชิงเทคนิค
งานประจำ (เพิ่มผู้ใช้ กำหนดบทบาท) ให้ใช้หน้า "ผู้ใช้และสิทธิ์" ของระบบแทน
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Department, LoginAttempt, Role, User, UserRole


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name_th", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name_th")


class UserRoleInline(admin.TabularInline):
    model = UserRole
    fk_name = "user"
    extra = 0
    fields = ("role", "department", "valid_from", "valid_to")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "display_name_th", "department", "clearance_level", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "department", "clearance_level")
    search_fields = ("username", "first_name_th", "last_name_th", "email")
    ordering = ("username",)
    inlines = [UserRoleInline]
    readonly_fields = ("mfa_confirmed_at",)
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "ข้อมูลหน่วยงาน",
            {"fields": ("first_name_th", "last_name_th", "position", "department", "clearance_level")},
        ),
        ("ความปลอดภัย", {"fields": ("must_change_password", "mfa_confirmed_at")}),
    )

    @admin.display(description="ชื่อ-นามสกุล")
    def display_name_th(self, obj):
        return obj.display_name_th


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name_th")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("created_at", "username", "ip_address", "stage", "success")
    list_filter = ("success", "stage")
    search_fields = ("username", "ip_address")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
