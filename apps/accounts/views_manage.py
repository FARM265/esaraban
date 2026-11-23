"""หน้าจัดการผู้ใช้ บทบาท และกลุ่มงาน สำหรับผู้ที่มีสิทธิ์ manage_users และหน้าบัญชีของฉัน"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.constants import RoleCode

from . import permissions, security
from .forms import DepartmentForm, RoleAssignForm, SetTempPasswordForm, UserCreateForm, UserEditForm
from .models import Department, UserRole
from .permissions import capability_required

User = get_user_model()
MANAGE = "manage_users"


def profile(request):
    user = request.user
    return render(
        request,
        "accounts/profile.html",
        {
            "assignments": permissions.active_roles(user),
            "backup_left": security.remaining_backup_codes(user),
            "capabilities": [
                label for cap, label in permissions.CAPABILITY_LABELS.items()
                if permissions.has_capability(user, cap)
            ],
        },
    )


# ---------------------------------------------------------------------------
# ผู้ใช้
# ---------------------------------------------------------------------------


@capability_required(MANAGE)
def user_list(request):
    qs = User.objects.select_related("department").order_by("username")
    q = request.GET.get("q", "").strip()
    dept = request.GET.get("department", "")
    status = request.GET.get("status", "active")
    if q:
        qs = qs.filter(
            Q(username__icontains=q) | Q(first_name_th__icontains=q) | Q(last_name_th__icontains=q)
        )
    if dept.isdigit():
        qs = qs.filter(department_id=int(dept))
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/users/list.html",
        {
            "page": page,
            "q": q,
            "department": dept,
            "status": status,
            "departments": Department.objects.filter(is_active=True),
        },
    )


def _audit(request, action, summary, target=None, **detail):
    from apps.audit import services as audit

    audit.record(
        "USER", action, summary, actor=request.user, target=target, ip=security.client_ip(request), **detail
    )


@capability_required(MANAGE)
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        _audit(request, "USER_CREATED", f"สร้างผู้ใช้ {user.username}", user)
        messages.success(
            request,
            f"สร้างผู้ใช้ {user.username} แล้ว ผู้ใช้ต้องตั้งค่า MFA และเปลี่ยนรหัสผ่านเมื่อเข้าสู่ระบบครั้งแรก",
        )
        return redirect("accounts:user_detail", pk=user.pk)
    return render(request, "accounts/users/form.html", {"form": form, "creating": True})


@capability_required(MANAGE)
def user_detail(request, pk):
    target = get_object_or_404(User.objects.select_related("department"), pk=pk)
    edit_form = UserEditForm(request.POST or None, instance=target, prefix="edit")
    if request.method == "POST":
        if edit_form.is_valid():
            edit_form.save()
            _audit(request, "USER_UPDATED", f"แก้ไขข้อมูลผู้ใช้ {target.username}", target,
                   fields=edit_form.changed_data)
            messages.success(request, "บันทึกข้อมูลผู้ใช้แล้ว")
            return redirect("accounts:user_detail", pk=target.pk)
        messages.error(request, "ยังไม่ได้บันทึก กรุณาแก้ไขช่องที่มีกรอบสีแดง")
    return render(
        request,
        "accounts/users/detail.html",
        {
            "target": target,
            "edit_form": edit_form,
            "role_form": RoleAssignForm(user=target, prefix="role"),
            "password_form": SetTempPasswordForm(target, prefix="pw"),
            "assignments": target.role_assignments.select_related("role", "department").order_by("role_id"),
            "backup_left": security.remaining_backup_codes(target),
            "is_self": target.pk == request.user.pk,
        },
    )


def _would_remove_last_admin(target, removing_assignment=None, deactivating=False):
    """กันไม่ให้ระบบไม่เหลือผู้ดูแลระบบเลย"""
    admins = UserRole.objects.active().filter(
        role__code=RoleCode.ADMIN, department__isnull=True, user__is_active=True
    )
    if removing_assignment is not None:
        admins = admins.exclude(pk=removing_assignment.pk)
    if deactivating:
        admins = admins.exclude(user=target)
    return not admins.exists() and not User.objects.filter(is_superuser=True, is_active=True).exclude(
        pk=target.pk if deactivating else None
    ).exists()


@capability_required(MANAGE)
@require_POST
def user_role_add(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = RoleAssignForm(request.POST, user=target, instance=UserRole(user=target), prefix="role")
    if form.is_valid():
        assignment = form.save(commit=False)
        assignment.granted_by = request.user
        assignment.save()
        _audit(request, "ROLE_GRANTED", f"เพิ่มบทบาท {assignment} ให้ {target.username}", target)
        messages.success(request, f"เพิ่มบทบาท {assignment} แล้ว")
    else:
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f"เพิ่มบทบาทไม่สำเร็จ: {errors}")
    return redirect("accounts:user_detail", pk=target.pk)


@capability_required(MANAGE)
@require_POST
def user_role_remove(request, pk, assignment_id):
    target = get_object_or_404(User, pk=pk)
    assignment = get_object_or_404(UserRole, pk=assignment_id, user=target)
    with transaction.atomic():
        if assignment.role.code == RoleCode.ADMIN and _would_remove_last_admin(target, removing_assignment=assignment):
            messages.error(request, "ลบไม่ได้ เพราะจะไม่เหลือผู้ดูแลระบบในระบบเลย")
        else:
            label = str(assignment)
            assignment.delete()
            _audit(request, "ROLE_REVOKED", f"ยกเลิกบทบาท {label} ของ {target.username}", target)
            messages.success(request, f"ยกเลิกบทบาท {label} แล้ว")
    return redirect("accounts:user_detail", pk=target.pk)


@capability_required(MANAGE)
@require_POST
def user_set_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = SetTempPasswordForm(target, request.POST, prefix="pw")
    if form.is_valid():
        form.save()
        _audit(request, "PASSWORD_RESET", f"ตั้งรหัสผ่านชั่วคราวให้ {target.username}", target)
        messages.success(request, f"ตั้งรหัสผ่านชั่วคราวให้ {target.username} แล้ว ผู้ใช้ต้องเปลี่ยนเมื่อเข้าสู่ระบบ")
    else:
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f"ตั้งรหัสผ่านไม่สำเร็จ: {errors}")
    return redirect("accounts:user_detail", pk=target.pk)


@capability_required(MANAGE)
@require_POST
def user_reset_mfa(request, pk):
    target = get_object_or_404(User, pk=pk)
    with transaction.atomic():
        target.reset_mfa()
        target.save(update_fields=["mfa_secret_encrypted", "mfa_confirmed_at", "mfa_last_used_step"])
        _audit(request, "MFA_RESET", f"รีเซ็ต MFA ของ {target.username}", target)
    messages.success(request, f"รีเซ็ต MFA ของ {target.username} แล้ว ผู้ใช้ต้องสแกน QR ใหม่ในการเข้าสู่ระบบครั้งถัดไป")
    return redirect("accounts:user_detail", pk=target.pk)


@capability_required(MANAGE)
@require_POST
def user_toggle_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "ไม่สามารถระงับบัญชีของตัวเองได้")
    elif target.is_active and _would_remove_last_admin(target, deactivating=True):
        messages.error(request, "ระงับไม่ได้ เพราะจะไม่เหลือผู้ดูแลระบบในระบบเลย")
    else:
        target.is_active = not target.is_active
        target.save(update_fields=["is_active"])
        _audit(request, "USER_ACTIVATED" if target.is_active else "USER_DEACTIVATED",
               f"{'เปิดใช้งาน' if target.is_active else 'ระงับ'}บัญชี {target.username}", target)
        messages.success(request, f"{'เปิดใช้งาน' if target.is_active else 'ระงับ'}บัญชี {target.username} แล้ว")
    return redirect("accounts:user_detail", pk=target.pk)


# ---------------------------------------------------------------------------
# กลุ่มงาน
# ---------------------------------------------------------------------------


@capability_required(MANAGE)
def department_list(request):
    departments = Department.objects.select_related("parent").order_by("code")
    return render(request, "accounts/departments/list.html", {"departments": departments})


@capability_required(MANAGE)
def department_edit(request, pk=None):
    instance = get_object_or_404(Department, pk=pk) if pk else None
    form = DepartmentForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        dept = form.save()
        _audit(request, "DEPARTMENT_SAVED", f"บันทึกกลุ่มงาน {dept.code} {dept.name_th}", dept)
        messages.success(request, f"บันทึกกลุ่มงาน {dept.name_th} แล้ว")
        return redirect("accounts:department_list")
    return render(request, "accounts/departments/form.html", {"form": form, "instance": instance})
