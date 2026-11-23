from django import forms

from apps.accounts.models import Department

from .models import RegisterBook

INPUT = {"class": "form-control"}


class IssueNumberForm(forms.Form):
    subject = forms.CharField(label="เรื่อง", max_length=500, widget=forms.TextInput(attrs=INPUT))
    recipient = forms.CharField(label="ถึง", max_length=300, required=False, widget=forms.TextInput(attrs=INPUT))


class VoidNumberForm(forms.Form):
    reason = forms.CharField(
        label="เหตุผลการยกเลิก",
        max_length=1000,
        widget=forms.Textarea(attrs={**INPUT, "rows": 2}),
    )


class RegisterBookForm(forms.ModelForm):
    class Meta:
        model = RegisterBook
        fields = ["code", "name_th", "register_type", "org_code", "number_format", "department", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs=INPUT),
            "name_th": forms.TextInput(attrs=INPUT),
            "register_type": forms.Select(attrs={"class": "form-select"}),
            "org_code": forms.TextInput(attrs=INPUT),
            "number_format": forms.TextInput(attrs={**INPUT, "style": "font-family: monospace"}),
            "department": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].empty_label = "ทั้งสำนักงาน"
        if self.instance.pk and self.instance.issued_numbers.exists():
            # เปลี่ยนประเภทหลังออกเลขแล้วจะทำให้ทะเบียนสับสน
            self.fields["register_type"].disabled = True
            self.fields["code"].disabled = True
