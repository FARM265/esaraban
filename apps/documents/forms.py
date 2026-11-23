from django import forms
from django.conf import settings

from apps.accounts.models import Department
from apps.core.constants import SecrecyLevel
from apps.registry.models import RegisterBook, RegisterType

from .models import Document
from .pdfcheck import PDFRejected, check_pdf

INPUT = {"class": "form-control"}
SELECT = {"class": "form-select"}
DATE = {"class": "form-control", "type": "date"}


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"class": "form-control", "accept": "application/pdf,.pdf", "multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data if d]
        return [single(data, initial)] if data else []


def _read_and_check(upload):
    """อ่านไฟล์และตรวจ คืนค่า (ชื่อไฟล์, bytes, จำนวนหน้า)"""
    if not upload.name.lower().endswith(".pdf"):
        raise forms.ValidationError(f"{upload.name}: รับเฉพาะไฟล์ .pdf")
    if upload.size > settings.ESARABAN_MAX_UPLOAD_BYTES:
        raise forms.ValidationError(f"{upload.name}: ไฟล์ใหญ่เกิน {settings.ESARABAN_MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    data = upload.read()
    try:
        pages = check_pdf(data, settings.ESARABAN_MAX_UPLOAD_BYTES)
    except PDFRejected as exc:
        raise forms.ValidationError(f"{upload.name}: {exc}") from exc
    # นับหน้าด้วย pypdf ซึ่งแม่นกว่า (PDF จาก Word มักบีบอัดโครงสร้างหน้าไว้)
    from apps.signatures.stamping import StampError, page_count

    try:
        pages = page_count(data)
    except StampError:
        pass
    return upload.name, data, pages


def secrecy_choices_for(user):
    allowed = []
    for value, label in SecrecyLevel.choices:
        if value > user.clearance_level:
            continue
        if value == SecrecyLevel.TOP_SECRET and not settings.ESARABAN_ALLOW_TOP_SECRET:
            continue
        allowed.append((value, label))
    return allowed


class _DocumentFields(forms.ModelForm):
    class Meta:
        model = Document
        fields = [
            "source_doc_no", "source_doc_date", "source_org", "subject", "recipient",
            "urgency", "secrecy", "owner_department", "due_date", "note",
        ]
        widgets = {
            "source_doc_no": forms.TextInput(attrs={**INPUT, "placeholder": "เช่น ตย 0000/1234"}),
            "source_doc_date": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
            "source_org": forms.TextInput(attrs=INPUT),
            "subject": forms.TextInput(attrs=INPUT),
            "recipient": forms.TextInput(attrs={**INPUT, "placeholder": "เช่น ผู้อำนวยการ"}),
            "urgency": forms.RadioSelect,
            "secrecy": forms.RadioSelect,
            "owner_department": forms.Select(attrs=SELECT),
            "due_date": forms.DateInput(attrs=DATE, format="%Y-%m-%d"),
            "note": forms.Textarea(attrs={**INPUT, "rows": 2}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for name in ("source_doc_no", "source_doc_date", "source_org"):
            self.fields[name].required = True
        self.fields["owner_department"].queryset = Department.objects.filter(is_active=True)
        self.fields["owner_department"].empty_label = "— ยังไม่ระบุ —"
        choices = secrecy_choices_for(user)
        current = getattr(self.instance, "secrecy", None)
        if self.instance.pk and current is not None and current not in dict(choices):
            choices.append((current, SecrecyLevel(current).label))
        self.fields["secrecy"].choices = choices

    def clean_secrecy(self):
        value = self.cleaned_data["secrecy"]
        if value not in dict(secrecy_choices_for(self.user)) and value != getattr(self.instance, "secrecy", None):
            raise forms.ValidationError("ท่านกำหนดชั้นความลับระดับนี้ไม่ได้")
        return value

    def clean(self):
        cleaned = super().clean()
        doc_date, due = cleaned.get("source_doc_date"), cleaned.get("due_date")
        if doc_date and due and due < doc_date:
            self.add_error("due_date", "กำหนดเสร็จต้องไม่ก่อนวันที่ของหนังสือ")
        return cleaned


class ReceiveForm(_DocumentFields):
    book = forms.ModelChoiceField(
        label="ชุดทะเบียนรับ",
        queryset=RegisterBook.objects.none(),
        widget=forms.Select(attrs=SELECT),
        empty_label=None,
    )
    main_file = forms.FileField(
        label="ไฟล์หนังสือ (ไฟล์หลัก)",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "application/pdf,.pdf"}),
    )
    extra_files = MultipleFileField(label="สิ่งที่ส่งมาด้วย", required=False)

    field_order = ["book", "main_file", "extra_files"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["book"].queryset = RegisterBook.objects.filter(register_type=RegisterType.RECEIVE, is_active=True)
        if self.user.department_id and not self.is_bound:
            self.initial.setdefault("owner_department", self.user.department_id)

    def clean_main_file(self):
        return _read_and_check(self.cleaned_data["main_file"])

    def clean_extra_files(self):
        files = self.cleaned_data.get("extra_files") or []
        if len(files) > settings.ESARABAN_MAX_FILES_PER_UPLOAD - 1:
            raise forms.ValidationError(f"แนบได้ไม่เกิน {settings.ESARABAN_MAX_FILES_PER_UPLOAD - 1} ไฟล์")
        return [_read_and_check(f) for f in files]

    def clean(self):
        cleaned = super().clean()
        main, extras = cleaned.get("main_file"), cleaned.get("extra_files") or []
        if main:
            total = len(main[1]) + sum(len(f[1]) for f in extras)
            if total > settings.ESARABAN_MAX_TOTAL_UPLOAD_BYTES:
                raise forms.ValidationError(
                    f"ไฟล์รวมกันใหญ่เกิน {settings.ESARABAN_MAX_TOTAL_UPLOAD_BYTES // (1024 * 1024)} MB"
                )
        return cleaned

    def document_data(self):
        return {name: self.cleaned_data[name] for name in self._meta.fields}


class DocumentEditForm(_DocumentFields):
    pass
