"""
เอกสารไม่เปิดให้แก้ผ่าน Django admin เพราะจะข้ามการตรวจสิทธิ์รายเอกสารและการบันทึกประวัติ
แสดงเฉพาะข้อมูลประวัติ (ไม่มีเนื้อหาเอกสาร) ให้ superuser ตรวจทางเทคนิค
"""
from django.contrib import admin

from .models import DocumentEvent


@admin.register(DocumentEvent)
class DocumentEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "ip_address")
    list_filter = ("action",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
