from django import forms

from apps.accounts.models import Department
from apps.documents.models import DocumentKind, DocumentStatus

from .registers import KINDS as REPORT_KINDS

SELECT = {"class": "form-select"}
INPUT = {"class": "form-control"}


class SearchForm(forms.Form):
    q = forms.CharField(label="คำค้น", required=False, max_length=200,
                        widget=forms.TextInput(attrs={**INPUT, "placeholder": "เลขทะเบียน เรื่อง หน่วยงาน ผู้รับ หรือข้อความในหนังสือ"}))
    kind = forms.ChoiceField(label="ประเภท", required=False, choices=[("", "ทั้งหมด"), *DocumentKind.choices],
                             widget=forms.Select(attrs=SELECT))
    status = forms.ChoiceField(label="สถานะ", required=False, choices=[("", "ทั้งหมด"), *DocumentStatus.choices],
                               widget=forms.Select(attrs=SELECT))
    department = forms.ModelChoiceField(label="กลุ่มงาน", required=False, queryset=Department.objects.filter(is_active=True),
                                        empty_label="ทั้งหมด", widget=forms.Select(attrs=SELECT))
    date_from = forms.DateField(label="ตั้งแต่วันที่", required=False, widget=forms.DateInput(attrs={**INPUT, "type": "date"}))
    date_to = forms.DateField(label="ถึงวันที่", required=False, widget=forms.DateInput(attrs={**INPUT, "type": "date"}))
    urgent = forms.BooleanField(label="เฉพาะเรื่องด่วน", required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    overdue = forms.BooleanField(label="เฉพาะเรื่องเกินกำหนด", required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    mine = forms.BooleanField(label="เฉพาะที่รอฉันดำเนินการ", required=False,
                              widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))


class ReportForm(forms.Form):
    kind = forms.ChoiceField(label="รายงาน", choices=REPORT_KINDS, initial="incoming", widget=forms.RadioSelect)
    date_from = forms.DateField(label="ตั้งแต่วันที่", widget=forms.DateInput(attrs={**INPUT, "type": "date"}))
    date_to = forms.DateField(label="ถึงวันที่", widget=forms.DateInput(attrs={**INPUT, "type": "date"}))
    department = forms.ModelChoiceField(label="กลุ่มงาน", required=False, queryset=Department.objects.filter(is_active=True),
                                        empty_label="ทุกกลุ่มงาน", widget=forms.Select(attrs=SELECT))
    overdue_only = forms.BooleanField(label="เฉพาะเรื่องเกินกำหนด (รายงานเรื่องค้าง)", required=False,
                                      widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    format = forms.ChoiceField(choices=[("xlsx", "Excel"), ("pdf", "PDF")], required=False)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and end and start > end:
            self.add_error("date_to", "วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น")
        return cleaned
