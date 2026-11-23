import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="mfa_secret_encrypted",
            field=models.TextField(blank=True, default="", editable=False, verbose_name="รหัส MFA (เข้ารหัส)"),
        ),
        migrations.AddField(
            model_name="user",
            name="mfa_confirmed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name="ตั้งค่า MFA เมื่อ"),
        ),
        migrations.AddField(
            model_name="user",
            name="mfa_last_used_step",
            field=models.BigIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                help_text="ตั้งอัตโนมัติเมื่อผู้ดูแลกำหนดรหัสผ่านชั่วคราวให้",
                verbose_name="ต้องเปลี่ยนรหัสผ่านเมื่อเข้าสู่ระบบ",
            ),
        ),
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "code",
                    models.CharField(
                        choices=[
                            ("ADMIN", "ผู้ดูแลระบบ"),
                            ("EXECUTIVE", "ผู้บริหาร"),
                            ("HEAD", "หัวหน้ากลุ่มงาน"),
                            ("CLERK", "เจ้าหน้าที่สารบรรณ"),
                            ("STAFF", "เจ้าหน้าที่ทั่วไป"),
                            ("AUDITOR", "ผู้ตรวจสอบ"),
                        ],
                        max_length=20,
                        unique=True,
                        verbose_name="รหัสบทบาท",
                    ),
                ),
                ("name_th", models.CharField(max_length=100, verbose_name="ชื่อบทบาท")),
            ],
            options={
                "verbose_name": "บทบาท",
                "verbose_name_plural": "บทบาท",
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="UserRole",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("valid_from", models.DateField(default=django.utils.timezone.localdate, verbose_name="มีผลตั้งแต่")),
                ("valid_to", models.DateField(blank=True, null=True, verbose_name="สิ้นสุด")),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        help_text="เว้นว่าง = ทั้งสำนักงาน",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="role_assignments",
                        to="accounts.department",
                        verbose_name="ขอบเขตกลุ่มงาน",
                    ),
                ),
                (
                    "granted_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "role",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignments",
                        to="accounts.role",
                        verbose_name="บทบาท",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="role_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "การมอบบทบาท",
                "verbose_name_plural": "การมอบบทบาท",
                "constraints": [
                    models.UniqueConstraint(fields=("user", "role", "department"), name="uniq_user_role_department"),
                    models.UniqueConstraint(
                        condition=models.Q(("department__isnull", True)),
                        fields=("user", "role"),
                        name="uniq_user_role_orgwide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("valid_to__isnull", True), ("valid_to__gte", models.F("valid_from")), _connector="OR"),
                        name="userrole_valid_range",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BackupCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code_hash", models.CharField(max_length=64)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="backup_codes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("user", "code_hash"), name="uniq_backup_code")],
            },
        ),
        migrations.CreateModel(
            name="LoginAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(db_index=True, max_length=150)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "stage",
                    models.CharField(
                        choices=[("PASSWORD", "รหัสผ่าน"), ("MFA", "รหัสยืนยัน")],
                        default="PASSWORD",
                        max_length=10,
                    ),
                ),
                ("success", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["username", "created_at"], name="loginattempt_user_time")],
            },
        ),
    ]
