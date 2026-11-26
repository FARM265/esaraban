from django import forms

from .models import Retention


NEW_FOLDER = "__new__"


class ArchiveForm(forms.Form):
    """เลือกหมวด/แฟ้มที่มีอยู่ หรือเลือก "สร้างหมวดใหม่" แล้วพิมพ์ชื่อ"""

    folder = forms.ChoiceField(label="หมวด/แฟ้ม", widget=forms.Select(attrs={"class": "form-select"}))
    new_folder = forms.CharField(
        label="ชื่อหมวดใหม่", max_length=200, required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "เช่น 2569/ร้องเรียน"}),
    )
    retention_years = forms.TypedChoiceField(
        label="อายุการเก็บ", coerce=int, choices=Retention.choices, initial=Retention.TEN,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    note = forms.CharField(label="หมายเหตุ", required=False, max_length=1000,
                           widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import ArchiveFolder

        names = list(ArchiveFolder.objects.values_list("name", flat=True))
        self.fields["folder"].choices = (
            [("", "เลือกหมวด/แฟ้ม")] if names else []
        ) + [(n, n) for n in names] + [(NEW_FOLDER, "+ สร้างหมวดใหม่")]
        if not names:
            self.fields["folder"].initial = NEW_FOLDER

    def clean(self):
        data = super().clean()
        if data.get("folder") == NEW_FOLDER:
            name = " ".join((data.get("new_folder") or "").split())
            if not name:
                self.add_error("new_folder", "กรุณาพิมพ์ชื่อหมวดใหม่")
            data["folder"] = name
        return data


class ReleaseForm(forms.Form):
    reason = forms.CharField(label="เหตุผลที่นำออก", max_length=1000,
                             widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}))
