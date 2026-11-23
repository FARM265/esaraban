"""สร้างบทบาท 6 แบบตามข้อกำหนด"""
from django.db import migrations

ROLES = [
    ("ADMIN", "ผู้ดูแลระบบ"),
    ("EXECUTIVE", "ผู้บริหาร"),
    ("HEAD", "หัวหน้ากลุ่มงาน"),
    ("CLERK", "เจ้าหน้าที่สารบรรณ"),
    ("STAFF", "เจ้าหน้าที่ทั่วไป"),
    ("AUDITOR", "ผู้ตรวจสอบ"),
]


def seed(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for code, name in ROLES:
        Role.objects.update_or_create(code=code, defaults={"name_th": name})


def give_existing_superusers_admin_role(apps, schema_editor):
    """superuser ที่สร้างไว้ในขั้นตอนที่ 4 จะได้บทบาทผู้ดูแลระบบ เพื่อให้เข้าหน้าจัดการผู้ใช้ได้"""
    User = apps.get_model("accounts", "User")
    Role = apps.get_model("accounts", "Role")
    UserRole = apps.get_model("accounts", "UserRole")
    admin_role = Role.objects.get(code="ADMIN")
    for user in User.objects.filter(is_superuser=True):
        UserRole.objects.get_or_create(user=user, role=admin_role, department=None)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_roles_mfa_lockout"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.RunPython(give_existing_superusers_admin_role, migrations.RunPython.noop),
    ]
