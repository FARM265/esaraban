from django import forms
from django.contrib.auth import get_user_model
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from .models import Decision, StepKind, WorkflowStep, WorkflowTemplate

User = get_user_model()
INPUT = {"class": "form-control"}
SELECT = {"class": "form-select"}


class StartForm(forms.Form):
    template = forms.ModelChoiceField(
        label="เส้นทางการเสนอ", queryset=WorkflowTemplate.objects.none(), widget=forms.Select(attrs=SELECT), empty_label=None
    )
    comment = forms.CharField(
        label="ความเห็นเสนอ (ถ้ามี)", required=False, max_length=2000, widget=forms.Textarea(attrs={**INPUT, "rows": 2})
    )

    def __init__(self, *args, document, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = WorkflowTemplate.objects.filter(is_active=True, doc_kind=document.kind)


class ActionForm(forms.Form):
    decision = forms.ChoiceField(choices=Decision.choices, widget=forms.HiddenInput)
    comment = forms.CharField(
        label="ความเห็น", required=False, max_length=4000, widget=forms.Textarea(attrs={**INPUT, "rows": 3})
    )
    command_text = forms.CharField(
        label="ข้อสั่งการ", required=False, max_length=4000, widget=forms.Textarea(attrs={**INPUT, "rows": 3})
    )
    assignees = forms.ModelMultipleChoiceField(
        label="ผู้รับผิดชอบ",
        required=False,
        queryset=User.objects.none(),
        widget=forms.SelectMultiple(attrs={**SELECT, "size": 6}),
        help_text="กด Ctrl ค้างไว้เพื่อเลือกหลายคน ถ้าไม่เลือก ระบบจะถือว่าเรื่องจบที่การสั่งการ (เช่น ทราบ / เก็บเข้าแฟ้ม)",
    )
    due_date = forms.DateField(
        label="กำหนดเสร็จ", required=False, widget=forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d")
    )

    def __init__(self, *args, document=None, **kwargs):
        super().__init__(*args, **kwargs)
        if document is not None:
            self.fields["assignees"].queryset = (
                User.objects.filter(is_active=True, clearance_level__gte=document.secrecy)
                .select_related("department")
                .order_by("department__code", "first_name_th", "username")
            )
        self.fields["assignees"].label_from_instance = lambda u: (
            f"{u.display_name_th}{' · ' + u.department.name_th if u.department_id else ''}"
        )

    def clean_due_date(self):
        value = self.cleaned_data.get("due_date")
        if value and value < timezone.localdate():
            raise forms.ValidationError("กำหนดเสร็จต้องไม่เป็นวันที่ผ่านมาแล้ว")
        return value


class WorkflowTemplateForm(forms.ModelForm):
    class Meta:
        model = WorkflowTemplate
        fields = ["name", "doc_kind", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs=INPUT),
            "doc_kind": forms.Select(attrs=SELECT),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class BaseStepFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        steps = [
            f.cleaned_data for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
        ]
        if not steps:
            raise forms.ValidationError("ต้องมีอย่างน้อย 1 ขั้นตอน")
        steps.sort(key=lambda s: s["order"])
        orders = [s["order"] for s in steps]
        if len(set(orders)) != len(orders):
            raise forms.ValidationError("ลำดับขั้นตอนซ้ำกัน")
        if steps[-1]["kind"] != StepKind.COMMAND:
            raise forms.ValidationError("ขั้นตอนสุดท้ายต้องเป็นการสั่งการ")
        if any(s["kind"] == StepKind.COMMAND for s in steps[:-1]):
            raise forms.ValidationError("การสั่งการต้องเป็นขั้นตอนสุดท้ายเท่านั้น")


StepFormSet = inlineformset_factory(
    WorkflowTemplate,
    WorkflowStep,
    formset=BaseStepFormSet,
    fields=["order", "role", "scope", "kind", "sla_hours"],
    widgets={
        "order": forms.NumberInput(attrs={**INPUT, "min": 1, "style": "max-width:80px"}),
        "role": forms.Select(attrs=SELECT),
        "scope": forms.Select(attrs=SELECT),
        "kind": forms.Select(attrs=SELECT),
        "sla_hours": forms.NumberInput(attrs={**INPUT, "min": 1, "style": "max-width:100px"}),
    },
    extra=2,
    can_delete=True,
)


class DelegationForm(forms.Form):
    delegator = forms.ModelChoiceField(
        label="ผู้มอบหมาย", queryset=User.objects.none(), widget=forms.Select(attrs=SELECT)
    )
    delegate = forms.ModelChoiceField(
        label="ผู้ปฏิบัติราชการแทน", queryset=User.objects.none(), widget=forms.Select(attrs=SELECT)
    )
    start_date = forms.DateField(label="ตั้งแต่วันที่", widget=forms.DateInput(attrs={**INPUT, "type": "date"}))
    end_date = forms.DateField(label="ถึงวันที่", widget=forms.DateInput(attrs={**INPUT, "type": "date"}))
    reason = forms.CharField(label="เหตุผล", max_length=300, widget=forms.TextInput(attrs={**INPUT, "placeholder": "เช่น ไปราชการ ลาพักผ่อน"}))

    def __init__(self, *args, user, can_manage_all, **kwargs):
        super().__init__(*args, **kwargs)
        active = User.objects.filter(is_active=True).order_by("first_name_th", "username")
        self.fields["delegate"].queryset = active
        if can_manage_all:
            self.fields["delegator"].queryset = active
        else:
            # ผู้ใช้ทั่วไปมอบหมายได้เฉพาะงานของตนเอง
            self.fields["delegator"].queryset = active.filter(pk=user.pk)
            self.fields["delegator"].initial = user.pk
        for name in ("delegator", "delegate"):
            self.fields[name].label_from_instance = lambda u: u.display_name_th

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น")
        if end and end < timezone.localdate():
            self.add_error("end_date", "วันสิ้นสุดผ่านมาแล้ว")
        if cleaned.get("delegator") and cleaned.get("delegator") == cleaned.get("delegate"):
            self.add_error("delegate", "มอบหมายให้ตัวเองไม่ได้")
        return cleaned
