"""
การลงนาม

SignatureImage     ภาพลายมือชื่อของผู้ใช้ (เข้ารหัสเก็บเหมือนไฟล์เอกสาร) ใช้ได้ครั้งละ 1 ภาพ
DocumentSignature  บันทึกการลงนามแต่ละครั้ง: ใคร ลงบนไฟล์ไหน ได้ไฟล์ใหม่อะไร และ hash ของทั้งสองไฟล์

TestCertificateAuthority  CA ทดสอบของระบบ (มีแถวเดียว สร้างอัตโนมัติเมื่อมีการลงนามดิจิทัลครั้งแรก)
SigningCertificate        ใบรับรองของผู้ลงนามแต่ละคน ออกโดย CA ทดสอบ กุญแจลับเข้ารหัสเก็บเหมือนไฟล์เอกสาร

sig_type แยกชัดเจนระหว่าง IMAGE (ภาพลายมือชื่อ) กับ DIGITAL (ลายมือชื่อดิจิทัลด้วยใบรับรอง)
ระบบห้ามแสดงหรือรายงานภาพลายมือชื่อว่าเป็น Digital Signature
ใบรับรองทั้งหมดเป็นใบรับรองทดสอบ ไม่มีผลทางกฎหมาย
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class SignatureImage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="signature_images")
    storage_key = models.CharField(max_length=255, unique=True, editable=False)
    sha256 = models.CharField(max_length=64, editable=False)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-uploaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(is_active=True), name="one_active_signature_image"
            ),
        ]


class TestCertificateAuthority(models.Model):
    cert_pem = models.TextField()
    key_storage_key = models.CharField(max_length=255, editable=False)
    key_sha256 = models.CharField(max_length=64, editable=False)
    fingerprint = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "CA ทดสอบ"
        verbose_name_plural = "CA ทดสอบ"


class SigningCertificate(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="signing_certificates")
    authority = models.ForeignKey(TestCertificateAuthority, on_delete=models.PROTECT, related_name="issued")
    cert_pem = models.TextField()
    key_storage_key = models.CharField(max_length=255, editable=False)
    key_sha256 = models.CharField(max_length=64, editable=False)
    fingerprint = models.CharField(max_length=64, unique=True)
    common_name = models.CharField(max_length=200)
    not_before = models.DateTimeField()
    not_after = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(is_active=True), name="one_active_signing_certificate"
            ),
        ]

    def __str__(self):
        return f"{self.common_name} ({self.fingerprint[:16]})"


class SignatureType(models.TextChoices):
    IMAGE = "IMAGE", "ภาพลายมือชื่อ"
    DIGITAL = "DIGITAL", "Digital Signature (ใบรับรอง)"


class DocumentSignature(models.Model):
    document = models.ForeignKey("documents.Document", on_delete=models.PROTECT, related_name="signatures")
    source_attachment = models.ForeignKey(
        "documents.Attachment", on_delete=models.PROTECT, related_name="signed_versions"
    )
    signed_attachment = models.OneToOneField(
        "documents.Attachment", on_delete=models.PROTECT, related_name="signature_record"
    )
    signer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="document_signatures")
    sig_type = models.CharField(max_length=10, choices=SignatureType.choices)
    signature_image = models.ForeignKey(SignatureImage, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    certificate = models.ForeignKey(
        SigningCertificate, null=True, blank=True, on_delete=models.PROTECT, related_name="signatures"
    )
    page = models.PositiveIntegerField()
    position = models.CharField(max_length=40, blank=True)
    source_sha256 = models.CharField(max_length=64)
    signed_sha256 = models.CharField(max_length=64)
    mfa_verified = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    signed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-signed_at"]

    def __str__(self):
        return f"{self.get_sig_type_display()} โดย {self.signer} ({self.signed_at:%Y-%m-%d %H:%M})"
