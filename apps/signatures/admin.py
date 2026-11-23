from django.contrib import admin

from .models import DocumentSignature


@admin.register(DocumentSignature)
class DocumentSignatureAdmin(admin.ModelAdmin):
    """ดูได้อย่างเดียว การลงนามต้องทำผ่านหน้าเอกสารเพื่อยืนยันตัวตนและบันทึกประวัติ"""

    list_display = ("signed_at", "signer", "sig_type", "page", "mfa_verified")
    list_filter = ("sig_type",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
