import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("documents", "0003_signed_copy"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SignatureImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("storage_key", models.CharField(editable=False, max_length=255, unique=True)),
                ("sha256", models.CharField(editable=False, max_length=64)),
                ("width", models.PositiveIntegerField()),
                ("height", models.PositiveIntegerField()),
                ("is_active", models.BooleanField(default=True)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="signature_images",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-uploaded_at"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(is_active=True), fields=("user",), name="one_active_signature_image"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="DocumentSignature",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "sig_type",
                    models.CharField(
                        choices=[("IMAGE", "ภาพลายมือชื่อ"), ("DIGITAL", "Digital Signature (ใบรับรอง)")], max_length=10
                    ),
                ),
                ("page", models.PositiveIntegerField()),
                ("position", models.CharField(blank=True, max_length=40)),
                ("source_sha256", models.CharField(max_length=64)),
                ("signed_sha256", models.CharField(max_length=64)),
                ("mfa_verified", models.BooleanField(default=False)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("signed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="signatures", to="documents.document"
                    ),
                ),
                (
                    "signature_image",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="signatures.signatureimage",
                    ),
                ),
                (
                    "signed_attachment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="signature_record",
                        to="documents.attachment",
                    ),
                ),
                (
                    "signer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document_signatures",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source_attachment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="signed_versions",
                        to="documents.attachment",
                    ),
                ),
            ],
            options={"ordering": ["-signed_at"]},
        ),
    ]
