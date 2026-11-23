from django import forms
from django.conf import settings

from .stamping import MAX_WIDTH_RATIO, MIN_WIDTH_RATIO

INPUT = {"class": "form-control"}


class SignatureUploadForm(forms.Form):
    image = forms.FileField(
        label="ภาพลายมือชื่อ",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/png,image/jpeg"}),
        help_text="PNG หรือ JPG ไม่เกิน 2 MB เซ็นบนกระดาษขาวด้วยปากกาสีเข้มแล้วถ่ายภาพหรือสแกน ระบบจะลบพื้นขาวให้อัตโนมัติ",
    )


class FinalCopyForm(forms.Form):
    """
    สร้างไฟล์ฉบับใหม่จากตัวดู PDF: ข้อความสั่งการ/เกษียนอ่านจากฐานข้อมูล ส่วนตำแหน่งลายเซ็นมาจากช่องซ่อน
    ไม่วางลายเซ็นก็ได้ (เว้นช่องตำแหน่งว่างทั้งหมด) ถ้าวางลายเซ็นต้องกรอกรหัสยืนยัน
    """

    page = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    x = forms.FloatField(min_value=0, max_value=1, required=False, widget=forms.HiddenInput)
    y = forms.FloatField(min_value=0, max_value=1, required=False, widget=forms.HiddenInput)
    w = forms.FloatField(min_value=MIN_WIDTH_RATIO, max_value=MAX_WIDTH_RATIO, required=False, widget=forms.HiddenInput)
    code = forms.CharField(label="รหัสยืนยัน 6 หลักจากแอป", max_length=6, required=False)
    sig_kind = forms.ChoiceField(
        choices=[("image", "ภาพลายมือชื่อ"), ("digital", "ลายมือชื่อดิจิทัล")], required=False,
    )

    def __init__(self, *args, attachment, **kwargs):
        super().__init__(*args, **kwargs)
        self.attachment = attachment

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        position = [cleaned.get(k) for k in ("page", "x", "y", "w")]
        if all(v is None for v in position):
            cleaned["signature"] = None
            return cleaned
        if any(v is None for v in position):
            raise forms.ValidationError("ตำแหน่งลายเซ็นไม่ครบ กรุณาวางลายเซ็นใหม่")
        pages = self.attachment.page_count
        if pages and cleaned["page"] > pages:
            raise forms.ValidationError(f"ไฟล์นี้มี {pages} หน้า")
        if settings.ESARABAN_SIGN_REQUIRE_OTP and (
            not (cleaned.get("code") or "").isdigit() or len(cleaned["code"]) != 6
        ):
            raise forms.ValidationError("กรุณากรอกรหัส 6 หลักจากแอปเพื่อยืนยันการลงนาม")
        cleaned["signature"] = {
            "page": cleaned["page"], "x": cleaned["x"], "y": cleaned["y"], "w": cleaned["w"],
            "digital": cleaned.get("sig_kind") == "digital",
        }
        return cleaned
