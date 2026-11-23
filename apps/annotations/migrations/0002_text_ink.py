from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("annotations", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="annotation",
            name="kind",
            field=models.CharField(
                choices=[("NOTE", "หมุดความเห็น"), ("TEXT", "ข้อความสั่งการ/เกษียน")], default="NOTE", max_length=10
            ),
        ),
        migrations.AddField(
            model_name="annotation",
            name="color",
            field=models.CharField(
                choices=[("blue", "น้ำเงิน"), ("red", "แดง"), ("black", "ดำ"), ("green", "เขียว")],
                default="blue",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="annotation",
            name="size",
            field=models.CharField(
                choices=[("S", "เล็ก"), ("M", "กลาง"), ("L", "ใหญ่")], default="M", max_length=2
            ),
        ),
    ]
