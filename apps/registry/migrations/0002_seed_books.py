"""ชุดทะเบียนเริ่มต้น 5 ชุด ผู้ดูแลระบบแก้ชื่อและรูปแบบเลขได้ภายหลัง"""
from django.conf import settings
from django.db import migrations

BOOKS = [
    ("RCV", "ทะเบียนรับกลาง", "RECEIVE", "{no}/{year}"),
    ("SND", "ทะเบียนหนังสือส่ง", "SEND", "{org}/{no}"),
    ("INT", "ทะเบียนบันทึกข้อความ", "INTERNAL", "{org}/{no}"),
    ("ORD", "ทะเบียนคำสั่ง", "ORDER", "{no}/{year}"),
    ("ANN", "ทะเบียนประกาศ", "ANNOUNCE", "{no}/{year}"),
]


def seed(apps, schema_editor):
    RegisterBook = apps.get_model("registry", "RegisterBook")
    org_code = getattr(settings, "ESARABAN_ORG_CODE", "ปช XXXX")
    for code, name, rtype, fmt in BOOKS:
        RegisterBook.objects.get_or_create(
            code=code,
            defaults={"name_th": name, "register_type": rtype, "number_format": fmt, "org_code": org_code},
        )


class Migration(migrations.Migration):

    dependencies = [("registry", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
