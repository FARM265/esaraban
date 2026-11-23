"""
ผู้ใช้ กลุ่มงาน บทบาท และข้อมูลการยืนยันตัวตน

- User ใช้ UUID เป็น primary key
- บทบาทกำหนดผ่าน UserRole ซึ่งระบุขอบเขตกลุ่มงานได้ (ว่าง = ทั้งสำนักงาน)
- รหัส MFA (TOTP secret) เก็บแบบเข้ารหัส และรหัสสำรองเก็บเป็น hash เท่านั้น
"""
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.core.constants import RoleCode, SecrecyLevel


class Department(models.Model):
    """กลุ่มงานภายในสำนักงาน ซ้อนกันได้ผ่าน parent"""

    code = models.CharField("รหัสกลุ่มงาน", max_length=20, unique=True)
    name_th = models.CharField("ชื่อกลุ่มงาน", max_length=200)
    parent = models.ForeignKey(
        "self",
        verbose_name="สังกัด",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    is_active = models.BooleanField("ใช้งานอยู่", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "กลุ่มงาน"
        verbose_name_plural = "กลุ่มงาน"

    def __str__(self):
        return self.name_th

    def ancestor_ids(self):
        """id ของกลุ่มงานนี้และกลุ่มงานแม่ทุกระดับ (ป้องกันวนซ้ำด้วยชุดที่เคยเห็น)"""
        ids, node = [], self
        while node is not None and node.pk not in ids:
            ids.append(node.pk)
            node = node.parent
        return ids


def department_with_descendants(dept_ids):
    """id ของกลุ่มงานที่ระบุ รวมกลุ่มงานย่อยทุกระดับ"""
    ids, frontier = set(dept_ids), list(dept_ids)
    while frontier:
        children = list(Department.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
        frontier = [c for c in children if c not in ids]
        ids.update(frontier)
    return ids


class User(AbstractUser):
    """ผู้ใช้ระบบ ใช้ UUID เป็น primary key เพื่อไม่ให้เดาลำดับผู้ใช้จาก URL ได้"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name_th = models.CharField("ชื่อ (ไทย)", max_length=100, blank=True)
    last_name_th = models.CharField("นามสกุล (ไทย)", max_length=100, blank=True)
    position = models.CharField("ตำแหน่ง", max_length=200, blank=True)
    department = models.ForeignKey(
        Department,
        verbose_name="กลุ่มงาน",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="members",
    )
    clearance_level = models.PositiveSmallIntegerField(
        "ระดับสิทธิ์ชั้นความลับ",
        choices=SecrecyLevel.choices,
        default=SecrecyLevel.NORMAL,
        help_text="ผู้ใช้เปิดได้เฉพาะเอกสารที่มีชั้นความลับไม่เกินระดับนี้",
    )

    # MFA (TOTP)
    mfa_secret_encrypted = models.TextField("รหัส MFA (เข้ารหัส)", blank=True, default="", editable=False)
    mfa_confirmed_at = models.DateTimeField("ตั้งค่า MFA เมื่อ", null=True, blank=True, editable=False)
    mfa_last_used_step = models.BigIntegerField(null=True, blank=True, editable=False)

    must_change_password = models.BooleanField(
        "ต้องเปลี่ยนรหัสผ่านเมื่อเข้าสู่ระบบ",
        default=False,
        help_text="ตั้งอัตโนมัติเมื่อผู้ดูแลกำหนดรหัสผ่านชั่วคราวให้",
    )

    class Meta:
        verbose_name = "ผู้ใช้"
        verbose_name_plural = "ผู้ใช้"

    @property
    def display_name_th(self):
        full = f"{self.first_name_th} {self.last_name_th}".strip()
        return full or self.get_full_name() or self.username

    @property
    def mfa_enabled(self):
        return bool(self.mfa_secret_encrypted and self.mfa_confirmed_at)

    def reset_mfa(self):
        self.mfa_secret_encrypted = ""
        self.mfa_confirmed_at = None
        self.mfa_last_used_step = None
        self.backup_codes.all().delete()

    def can_view_secrecy(self, level):
        """ตรวจระดับชั้นความลับเท่านั้น สิทธิ์รายเอกสารจะเพิ่มในขั้นตอนที่ 6"""
        return self.is_active and int(level) <= self.clearance_level

    def __str__(self):
        return self.display_name_th


class Role(models.Model):
    """บทบาท 6 แบบตามข้อกำหนด สร้างโดย migration ไม่ให้เพิ่มหรือลบผ่านหน้าจอ"""

    code = models.CharField("รหัสบทบาท", max_length=20, unique=True, choices=RoleCode.choices)
    name_th = models.CharField("ชื่อบทบาท", max_length=100)

    class Meta:
        ordering = ["id"]
        verbose_name = "บทบาท"
        verbose_name_plural = "บทบาท"

    def __str__(self):
        return self.name_th


class UserRoleQuerySet(models.QuerySet):
    def active(self, on_date=None):
        today = on_date or timezone.localdate()
        return self.filter(valid_from__lte=today).filter(
            models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=today)
        )


class UserRole(models.Model):
    """การมอบบทบาทให้ผู้ใช้ ระบุกลุ่มงานเพื่อจำกัดขอบเขต หรือเว้นว่างเพื่อใช้ได้ทั้งสำนักงาน"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments", verbose_name="บทบาท")
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments",
        verbose_name="ขอบเขตกลุ่มงาน",
        help_text="เว้นว่าง = ทั้งสำนักงาน",
    )
    valid_from = models.DateField("มีผลตั้งแต่", default=timezone.localdate)
    valid_to = models.DateField("สิ้นสุด", null=True, blank=True)
    granted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    objects = UserRoleQuerySet.as_manager()

    class Meta:
        verbose_name = "การมอบบทบาท"
        verbose_name_plural = "การมอบบทบาท"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "department"], name="uniq_user_role_department"
            ),
            models.UniqueConstraint(
                fields=["user", "role"],
                condition=models.Q(department__isnull=True),
                name="uniq_user_role_orgwide",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=models.F("valid_from")),
                name="userrole_valid_range",
            ),
        ]

    def __str__(self):
        scope = self.department.name_th if self.department_id else "ทั้งสำนักงาน"
        return f"{self.role.name_th} ({scope})"


class BackupCode(models.Model):
    """รหัสสำรองสำหรับเข้าสู่ระบบเมื่อไม่มีมือถือ ใช้ได้ครั้งเดียว เก็บเป็น HMAC เท่านั้น"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "code_hash"], name="uniq_backup_code")]


class LoginAttempt(models.Model):
    """ประวัติการพยายามเข้าสู่ระบบ ใช้สำหรับล็อกบัญชีชั่วคราว (ขั้นตอนที่ 8 จะรวมเข้า Audit Log)"""

    class Stage(models.TextChoices):
        PASSWORD = "PASSWORD", "รหัสผ่าน"
        MFA = "MFA", "รหัสยืนยัน"

    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    stage = models.CharField(max_length=10, choices=Stage.choices, default=Stage.PASSWORD)
    success = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["username", "created_at"], name="loginattempt_user_time")]
