from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("documents", "0004_endorsed_event")]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "ร่าง"),
                    ("REGISTERED", "ลงทะเบียนแล้ว"),
                    ("IN_REVIEW", "อยู่ระหว่างเสนอ"),
                    ("RETURNED", "ส่งกลับแก้ไข"),
                    ("PENDING_SIGNATURE", "รอลงนาม"),
                    ("COMMANDED", "สั่งการแล้ว"),
                    ("IN_PROGRESS", "ดำเนินการ"),
                    ("DONE", "เสร็จสิ้น"),
                    ("ARCHIVED", "จัดเก็บ"),
                    ("CANCELLED", "ยกเลิก"),
                ],
                default="REGISTERED",
                max_length=20,
                verbose_name="สถานะ",
            ),
        ),
        migrations.AlterField(
            model_name="documentevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("REGISTERED", "ลงทะเบียน"),
                    ("UPDATED", "แก้ไขข้อมูล"),
                    ("FILE_ADDED", "เพิ่มไฟล์"),
                    ("VIEWED", "เปิดดูไฟล์"),
                    ("DOWNLOADED", "ดาวน์โหลดไฟล์"),
                    ("CANCELLED", "ยกเลิก"),
                    ("WF_STARTED", "เริ่มเสนอ"),
                    ("WF_FORWARD", "เสนอต่อ"),
                    ("WF_RETURN", "ส่งกลับแก้ไข"),
                    ("WF_RESUBMIT", "เสนออีกครั้ง"),
                    ("WF_COMMAND", "สั่งการ"),
                    ("WF_COMPLETE", "ดำเนินการเสร็จ"),
                    ("WF_CANCEL", "ยกเลิกการเสนอ"),
                    ("SIGNED", "ลงนาม"),
                    ("ENDORSED", "สั่งการ/เกษียน"),
                    ("DRAFTED", "สร้างร่างหนังสือ"),
                    ("DRAFT_REVISED", "แก้ไขร่างหนังสือ"),
                    ("NUMBER_ISSUED", "ออกเลขหนังสือ"),
                ],
                max_length=20,
            ),
        ),
    ]
