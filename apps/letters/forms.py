from django import forms

from apps.accounts.models import Department
from apps.documents.forms import secrecy_choices_for
from apps.documents.models import Document

from .models import LETTER_KINDS, LetterContent, Letterhead

INPUT = {"class": "form-control"}
SELECT = {"class": "form-select"}

# ช่องที่ใช้เฉพาะบางแม่แบบ (หน้าจอซ่อนช่องที่ไม่เกี่ยวข้อง และเซิร์ฟเวอร์ไม่บันทึกค่าของช่องเหล่านั้น)
KIND_FIELDS = {
    "recipient": {"OUTGOING", "INTERNAL"},
    "reference": {"OUTGOING"},
    "enclosures": {"OUTGOING"},
    "closing": {"OUTGOING"},
    "contact": {"OUTGOING"},
    "department_line": {"INTERNAL"},
}
DOCUMENT_FIELDS = ["subject", "recipient", "urgency", "secrecy", "owner_department"]
CONTENT_FIELDS = [
    "reference", "enclosures", "body", "closing", "signer_name", "signer_position", "department_line", "contact",
]


class LetterForm(forms.Form):
    kind = forms.ChoiceField(label="แม่แบบ", choices=LETTER_KINDS, widget=forms.RadioSelect)
    subject = forms.CharField(label="เรื่อง", max_length=500, widget=forms.TextInput(attrs=INPUT))
    recipient = forms.CharField(
        label="เรียน", max_length=300, required=False,
        widget=forms.TextInput(attrs={**INPUT, "placeholder": "เช่น ผู้อำนวยการ..."}),
    )
    reference = forms.CharField(label="อ้างถึง", max_length=500, required=False, widget=forms.TextInput(attrs=INPUT))
    enclosures = forms.CharField(
        label="สิ่งที่ส่งมาด้วย", required=False, help_text="บรรทัดละ 1 รายการ",
        widget=forms.Textarea(attrs={**INPUT, "rows": 2}),
    )
    body = forms.CharField(
        label="ข้อความ", max_length=20000,
        help_text="ขึ้นบรรทัดใหม่ = ขึ้นย่อหน้าใหม่ ระบบตัดคำ ย่อหน้า และขึ้นหน้าใหม่ให้อัตโนมัติ",
        widget=forms.Textarea(attrs={**INPUT, "rows": 10}),
    )
    closing = forms.CharField(label="คำลงท้าย", max_length=100, required=False, widget=forms.TextInput(attrs=INPUT))
    signer_name = forms.CharField(
        label="ชื่อผู้ลงนาม", max_length=200, required=False, help_text="ไม่ต้องใส่วงเล็บ ระบบใส่ให้",
        widget=forms.TextInput(attrs=INPUT),
    )
    signer_position = forms.CharField(
        label="ตำแหน่งผู้ลงนาม", required=False, help_text="บรรทัดละ 1 บรรทัด",
        widget=forms.Textarea(attrs={**INPUT, "rows": 2}),
    )
    department_line = forms.CharField(
        label="ส่วนราชการ", max_length=300, required=False, help_text="เช่น กลุ่มงาน... โทร. ...",
        widget=forms.TextInput(attrs=INPUT),
    )
    contact = forms.CharField(
        label="ส่วนราชการเจ้าของเรื่อง (มุมล่างซ้าย)", required=False, help_text="บรรทัดละ 1 บรรทัด เช่น กลุ่มงาน... / โทร. ...",
        widget=forms.Textarea(attrs={**INPUT, "rows": 2}),
    )
    owner_department = forms.ModelChoiceField(
        label="กลุ่มงานเจ้าของเรื่อง", queryset=Department.objects.none(), widget=forms.Select(attrs=SELECT),
    )
    urgency = forms.TypedChoiceField(
        label="ความเร่งด่วน", coerce=int, choices=Document._meta.get_field("urgency").choices,
        widget=forms.RadioSelect, initial=0,
    )
    secrecy = forms.TypedChoiceField(label="ชั้นความลับ", coerce=int, widget=forms.RadioSelect, initial=0)

    def __init__(self, *args, user, document=None, **kwargs):
        self.user = user
        self.document = document
        if document is not None and "initial" not in kwargs:
            letter = document.letter
            initial = {f: getattr(document, f) for f in DOCUMENT_FIELDS}
            initial.update({f: getattr(letter, f) for f in CONTENT_FIELDS})
            initial["owner_department"] = document.owner_department_id
            initial["kind"] = document.kind
            kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.fields["owner_department"].queryset = Department.objects.filter(is_active=True)
        if document is None:
            head = Letterhead.current()
            self.initial.setdefault("closing", "ขอแสดงความนับถือ")
            self.initial.setdefault("contact", head.default_contact)
            if user.department_id:
                self.initial.setdefault("owner_department", user.department_id)
        else:
            # เปลี่ยนแม่แบบหลังสร้างแล้วไม่ได้ เพราะเลขทะเบียนผูกกับประเภทหนังสือ
            self.fields["kind"].disabled = True
        choices = secrecy_choices_for(user)
        current = getattr(document, "secrecy", None)
        if current is not None and current not in dict(choices):
            choices.append((current, dict(Document._meta.get_field("secrecy").choices)[current]))
        self.fields["secrecy"].choices = choices

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        if kind:
            for name, kinds in KIND_FIELDS.items():
                if kind not in kinds:
                    cleaned[name] = ""
            if kind in KIND_FIELDS["recipient"] and not cleaned.get("recipient"):
                self.add_error("recipient", "กรุณาระบุผู้รับ (เรียน)")
        if not LetterContent.lines(cleaned.get("body", "")):
            self.add_error("body", "กรุณาพิมพ์ข้อความ")
        return cleaned

    def document_data(self):
        return {f: self.cleaned_data[f] for f in DOCUMENT_FIELDS}

    def content_data(self):
        return {f: self.cleaned_data[f].strip() for f in CONTENT_FIELDS}


class IssueForm(forms.Form):
    book = forms.ModelChoiceField(label="ชุดทะเบียน", queryset=None, empty_label=None, widget=forms.Select(attrs=SELECT))

    def __init__(self, *args, books, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["book"].queryset = books


class LetterheadForm(forms.ModelForm):
    emblem = forms.FileField(
        label="ภาพตราครุฑ", required=False,
        help_text="PNG หรือ JPG ไม่เกิน 2 MB ใช้ภาพจากหน่วยงานของท่าน ระบบลบพื้นขาวให้อัตโนมัติ",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/png,image/jpeg"}),
    )

    class Meta:
        model = Letterhead
        fields = ["org_name", "address", "default_contact"]
        widgets = {
            "org_name": forms.TextInput(attrs=INPUT),
            "address": forms.Textarea(attrs={**INPUT, "rows": 3}),
            "default_contact": forms.Textarea(attrs={**INPUT, "rows": 2}),
        }
