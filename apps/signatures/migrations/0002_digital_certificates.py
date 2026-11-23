import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("signatures", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TestCertificateAuthority",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cert_pem", models.TextField()),
                ("key_storage_key", models.CharField(editable=False, max_length=255)),
                ("key_sha256", models.CharField(editable=False, max_length=64)),
                ("fingerprint", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"verbose_name": "CA ทดสอบ", "verbose_name_plural": "CA ทดสอบ"},
        ),
        migrations.CreateModel(
            name="SigningCertificate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cert_pem", models.TextField()),
                ("key_storage_key", models.CharField(editable=False, max_length=255)),
                ("key_sha256", models.CharField(editable=False, max_length=64)),
                ("fingerprint", models.CharField(max_length=64, unique=True)),
                ("common_name", models.CharField(max_length=200)),
                ("not_before", models.DateTimeField()),
                ("not_after", models.DateTimeField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("authority", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issued", to="signatures.testcertificateauthority")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="signing_certificates", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(condition=models.Q(("is_active", True)), fields=("user",), name="one_active_signing_certificate"),
                ],
            },
        ),
        migrations.AddField(
            model_name="documentsignature",
            name="certificate",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="signatures", to="signatures.signingcertificate"),
        ),
    ]
