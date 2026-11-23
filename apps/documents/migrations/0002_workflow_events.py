from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("documents", "0001_initial")]

    operations = [
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
                ],
                max_length=20,
            ),
        ),
    ]
