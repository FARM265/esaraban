import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("documents", "0005_letters"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Letterhead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("org_name", models.CharField(max_length=200, verbose_name="ชื่อส่วนราชการ")),
                ("address", models.TextField(blank=True, help_text="บรรทัดละ 1 ส่วน เช่น เลขที่และถนน / อำเภอ จังหวัด รหัสไปรษณีย์", verbose_name="ที่ตั้ง")),
                ("default_contact", models.TextField(blank=True, help_text="แสดงมุมล่างซ้ายของหนังสือภายนอก เช่น กลุ่มงาน... / โทร. ... ผู้สร้างหนังสือแก้ไขได้ทุกฉบับ", verbose_name="ส่วนราชการเจ้าของเรื่อง (ค่าเริ่มต้น)")),
                ("emblem_key", models.CharField(blank=True, editable=False, max_length=255)),
                ("emblem_sha256", models.CharField(blank=True, editable=False, max_length=64)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "หัวหนังสือ", "verbose_name_plural": "หัวหนังสือ"},
        ),
        migrations.CreateModel(
            name="LetterContent",
            fields=[
                ("document", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True, related_name="letter", serialize=False, to="documents.document")),
                ("reference", models.CharField(blank=True, max_length=500, verbose_name="อ้างถึง")),
                ("enclosures", models.TextField(blank=True, help_text="บรรทัดละ 1 รายการ", verbose_name="สิ่งที่ส่งมาด้วย")),
                ("body", models.TextField(help_text="ขึ้นบรรทัดใหม่ = ขึ้นย่อหน้าใหม่ ระบบตัดคำและย่อหน้าให้อัตโนมัติ", verbose_name="ข้อความ")),
                ("closing", models.CharField(blank=True, default="ขอแสดงความนับถือ", max_length=100, verbose_name="คำลงท้าย")),
                ("signer_name", models.CharField(blank=True, help_text="ไม่ต้องใส่วงเล็บ", max_length=200, verbose_name="ชื่อผู้ลงนาม")),
                ("signer_position", models.TextField(blank=True, help_text="บรรทัดละ 1 บรรทัด", verbose_name="ตำแหน่งผู้ลงนาม")),
                ("department_line", models.CharField(blank=True, help_text="บันทึกข้อความ: เช่น กลุ่มงาน... โทร. ...", max_length=300, verbose_name="ส่วนราชการ")),
                ("contact", models.TextField(blank=True, help_text="หนังสือภายนอก: บรรทัดละ 1 บรรทัด", verbose_name="ส่วนราชการเจ้าของเรื่อง")),
                ("number_anchor", models.JSONField(blank=True, editable=False, null=True)),
                ("date_anchor", models.JSONField(blank=True, editable=False, null=True)),
                ("sign_anchor", models.JSONField(blank=True, editable=False, null=True)),
                ("letter_date", models.DateField(blank=True, editable=False, null=True, verbose_name="ลงวันที่")),
                ("revision", models.PositiveIntegerField(default=1, editable=False)),
            ],
            options={"verbose_name": "เนื้อหาหนังสือ", "verbose_name_plural": "เนื้อหาหนังสือ"},
        ),
    ]
