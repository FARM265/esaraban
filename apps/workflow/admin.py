"""ข้อมูล workflow ดูได้อย่างเดียวผ่าน Django admin การเปลี่ยนแปลงต้องทำผ่านหน้าจอของระบบเพื่อให้มีประวัติครบ"""
from django.contrib import admin

from .models import Delegation, WorkflowInstance, WorkflowTask


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkflowInstance)
class WorkflowInstanceAdmin(ReadOnlyAdmin):
    list_display = ("template_name", "status", "current_step", "started_by", "started_at")
    list_filter = ("status",)


@admin.register(WorkflowTask)
class WorkflowTaskAdmin(ReadOnlyAdmin):
    list_display = ("kind", "status", "role", "assignee", "decision", "acted_by", "on_behalf_of", "created_at")
    list_filter = ("kind", "status")


@admin.register(Delegation)
class DelegationAdmin(ReadOnlyAdmin):
    list_display = ("delegator", "delegate", "start_date", "end_date", "revoked_at")
