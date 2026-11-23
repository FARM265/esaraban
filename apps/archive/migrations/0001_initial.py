import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("documents", "0006_archive_events"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ArchiveRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("folder", models.CharField(max_length=200, verbose_name="หมวด/แฟ้ม")),
                ("retention_years", models.PositiveSmallIntegerField(choices=[(1, "1 ปี"), (5, "5 ปี"), (10, "10 ปี (ทั่วไป)"), (20, "20 ปี"), (0, "เก็บตลอดไป")], default=10, verbose_name="อายุการเก็บ")),
                ("keep_until", models.DateField(blank=True, null=True, verbose_name="เก็บถึง")),
                ("note", models.TextField(blank=True, verbose_name="หมายเหตุ")),
                ("previous_status", models.CharField(max_length=20)),
                ("archived_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("release_reason", models.TextField(blank=True)),
                ("archived_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="archive_records", to="documents.document")),
                ("released_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-archived_at"],
                "constraints": [models.UniqueConstraint(condition=models.Q(("released_at__isnull", True)), fields=("document",), name="one_active_archive_record")],
            },
        ),
    ]
