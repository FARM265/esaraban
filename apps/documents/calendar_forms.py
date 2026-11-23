from django import forms
from django.conf import settings

from .pdfcheck import PDFRejected, check_pdf

INPUT = {"class": "form-control"}


class CalendarUploadForm(forms.Form):
    file = forms.FileField(label="ไฟล์หนังสือ (PDF)", widget=forms.ClearableFileInput(attrs={**INPUT, "accept": "application/pdf"}))
    force_ocr = forms.BooleanField(
        label="อ่านจากภาพ (OCR) เสมอ ใช้เมื่ออ่านแบบปกติแล้วข้อมูลเพี้ยน", required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        data = upload.read()
        try:
            check_pdf(data, settings.ESARABAN_MAX_UPLOAD_BYTES)
        except PDFRejected as exc:
            raise forms.ValidationError(str(exc)) from exc
        return data


class AppointmentForm(forms.Form):
    title = forms.CharField(label="ชื่องาน", max_length=200, widget=forms.TextInput(attrs=INPUT))
    start_date = forms.DateField(label="วันที่", widget=forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"))
    end_date = forms.DateField(
        label="ถึงวันที่ (ถ้าหลายวัน)", required=False,
        widget=forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
    )
    start_time = forms.TimeField(
        label="เวลาเริ่ม", required=False, help_text="เว้นว่าง = ทั้งวัน",
        widget=forms.TimeInput(attrs={**INPUT, "type": "time"}, format="%H:%M"),
    )
    end_time = forms.TimeField(label="เวลาสิ้นสุด", required=False, widget=forms.TimeInput(attrs={**INPUT, "type": "time"}, format="%H:%M"))
    location = forms.CharField(label="สถานที่", max_length=200, required=False, widget=forms.TextInput(attrs=INPUT))
    subject = forms.CharField(label="เรื่อง", max_length=300, required=False, widget=forms.TextInput(attrs=INPUT))
    details = forms.CharField(label="รายละเอียดเพิ่มเติม", max_length=1000, required=False, widget=forms.Textarea(attrs={**INPUT, "rows": 3}))
    not_secret = forms.BooleanField(
        label="ยืนยันว่าหนังสือนี้ไม่มีชั้นความลับ (ข้อมูลจะถูกส่งไปยัง Google)", required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, require_not_secret=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_not_secret = require_not_secret
        if not require_not_secret:
            del self.fields["not_secret"]

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่ม")
        t1, t2 = cleaned.get("start_time"), cleaned.get("end_time")
        if t2 and not t1:
            self.add_error("start_time", "ใส่เวลาเริ่มด้วย หรือเว้นว่างทั้งสองช่องถ้าเป็นงานทั้งวัน")
        if t1 and t2 and t2 <= t1 and not (end and end > start):
            self.add_error("end_time", "เวลาสิ้นสุดต้องหลังเวลาเริ่ม")
        return cleaned
