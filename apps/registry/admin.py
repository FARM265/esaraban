from django.contrib import admin

from .models import IssuedNumber, RegisterBook


@admin.register(RegisterBook)
class RegisterBookAdmin(admin.ModelAdmin):
    list_display = ("code", "name_th", "register_type", "number_format", "is_active")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IssuedNumber)
class IssuedNumberAdmin(admin.ModelAdmin):
    """ดูได้อย่างเดียว การออกและยกเลิกเลขต้องทำผ่านหน้าทะเบียนเลขเพื่อให้มีร่องรอยครบ"""

    list_display = ("display_no", "book", "year_be", "status", "issued_by", "issued_at")
    list_filter = ("book", "year_be", "status")
    search_fields = ("display_no", "subject")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
