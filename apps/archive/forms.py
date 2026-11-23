from django import forms

from .models import Retention


class ArchiveForm(forms.Form):
    folder = forms.CharField(
        label="หมวด/แฟ้ม", max_length=200,
        widget=forms.TextInput(attrs={"class": "form-control", "list": "archive-folders", "placeholder": "เช่น 2569/ร้องเรียน"}),
    )
    retention_years = forms.TypedChoiceField(
        label="อายุการเก็บ", coerce=int, choices=Retention.choices, initial=Retention.TEN,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    note = forms.CharField(label="หมายเหตุ", required=False, max_length=1000,
                           widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))


class ReleaseForm(forms.Form):
    reason = forms.CharField(label="เหตุผลที่นำออก", max_length=1000,
                             widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))
