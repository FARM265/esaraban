from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm

from .models import Department, Role, UserRole

User = get_user_model()

INPUT = {"class": "form-control"}
SELECT = {"class": "form-select"}


class LoginForm(forms.Form):
    username = forms.CharField(
        label="ชื่อผู้ใช้",
        max_length=150,
        widget=forms.TextInput(attrs={**INPUT, "autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label="รหัสผ่าน",
        strip=False,
        widget=forms.PasswordInput(attrs={**INPUT, "autocomplete": "current-password"}),
    )


class OTPForm(forms.Form):
    code = forms.CharField(
        label="รหัสยืนยัน",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                **INPUT,
                "class": "form-control otp-input",
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "autofocus": True,
            }
        ),
    )


class PasswordChangeForm(DjangoPasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {
            "old_password": "รหัสผ่านปัจจุบัน",
            "new_password1": "รหัสผ่านใหม่",
            "new_password2": "ยืนยันรหัสผ่านใหม่",
        }
        for name, field in self.fields.items():
            field.label = labels[name]
            field.widget.attrs.update(INPUT)


class _TempPasswordMixin(forms.Form):
    password1 = forms.CharField(
        label="รหัสผ่านชั่วคราว",
        strip=False,
        widget=forms.PasswordInput(attrs={**INPUT, "autocomplete": "new-password"}),
        help_text="ผู้ใช้ต้องเปลี่ยนรหัสผ่านเองทันทีที่เข้าสู่ระบบครั้งแรก",
    )
    password2 = forms.CharField(
        label="ยืนยันรหัสผ่านชั่วคราว",
        strip=False,
        widget=forms.PasswordInput(attrs={**INPUT, "autocomplete": "new-password"}),
    )

    def clean_password2(self):
        p1, p2 = self.cleaned_data.get("password1"), self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("รหัสผ่านทั้งสองช่องไม่ตรงกัน")
        return p2


class UserProfileFields(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "username",
            "first_name_th",
            "last_name_th",
            "position",
            "email",
            "department",
            "clearance_level",
        ]
        labels = {"username": "ชื่อผู้ใช้", "email": "อีเมล"}
        widgets = {
            "username": forms.TextInput(attrs=INPUT),
            "first_name_th": forms.TextInput(attrs=INPUT),
            "last_name_th": forms.TextInput(attrs=INPUT),
            "position": forms.TextInput(attrs=INPUT),
            "email": forms.EmailInput(attrs=INPUT),
            "department": forms.Select(attrs=SELECT),
            "clearance_level": forms.Select(attrs=SELECT),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].label = "กลุ่มงานที่สังกัด"
        self.fields["department"].empty_label = "— ไม่สังกัดกลุ่มงาน —"
        self.fields["first_name_th"].required = True
        self.fields["last_name_th"].required = True


class UserCreateForm(UserProfileFields, _TempPasswordMixin):
    def _post_clean(self):
        super()._post_clean()
        password = self.cleaned_data.get("password2")
        if password:
            try:
                password_validation.validate_password(password, self.instance)
            except forms.ValidationError as error:
                self.add_error("password2", error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.must_change_password = True
        if commit:
            user.save()
        return user


class UserEditForm(UserProfileFields):
    pass


class SetTempPasswordForm(_TempPasswordMixin):
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password2(self):
        password = super().clean_password2()
        password_validation.validate_password(password, self.user)
        return password

    def save(self):
        self.user.set_password(self.cleaned_data["password1"])
        self.user.must_change_password = True
        self.user.save(update_fields=["password", "must_change_password"])
        return self.user


class RoleAssignForm(forms.ModelForm):
    class Meta:
        model = UserRole
        fields = ["role", "department", "valid_from", "valid_to"]
        widgets = {
            "role": forms.Select(attrs=SELECT),
            "department": forms.Select(attrs=SELECT),
            "valid_from": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
            "valid_to": forms.DateInput(attrs={**INPUT, "type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.target_user = user
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.all()
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["department"].empty_label = "ทั้งสำนักงาน"

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("valid_from"), cleaned.get("valid_to")
        if start and end and end < start:
            self.add_error("valid_to", "วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น")
        role, dept = cleaned.get("role"), cleaned.get("department")
        if role and self.target_user is not None:
            exists = UserRole.objects.filter(user=self.target_user, role=role, department=dept).exists()
            if exists:
                raise forms.ValidationError("ผู้ใช้มีบทบาทนี้ในขอบเขตนี้อยู่แล้ว")
        return cleaned


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["code", "name_th", "parent", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs=INPUT),
            "name_th": forms.TextInput(attrs=INPUT),
            "parent": forms.Select(attrs=SELECT),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Department.objects.all()
        if self.instance.pk:
            # ห้ามเลือกตัวเองหรือกลุ่มงานย่อยของตัวเองเป็นสังกัด (กันวนซ้ำ)
            qs = qs.exclude(pk__in=_descendant_ids(self.instance))
        self.fields["parent"].queryset = qs
        self.fields["parent"].empty_label = "— ไม่มี (ระดับบนสุด) —"


def _descendant_ids(department):
    ids, frontier = {department.pk}, [department.pk]
    while frontier:
        children = list(Department.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
        frontier = [c for c in children if c not in ids]
        ids.update(frontier)
    return ids
