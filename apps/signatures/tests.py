import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from apps.accounts import security, totp
from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_user
from apps.core.constants import RoleCode, SecrecyLevel
from apps.documents import storage
from apps.documents.models import Attachment, DocumentEvent
from apps.documents.services import register_incoming
from apps.registry.models import RegisterBook

from . import services
from .models import DocumentSignature, SignatureImage, SignatureType

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-sig-"))


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


def real_pdf(pages=2):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    for n in range(pages):
        c.drawString(72, 800, f"Test page {n + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def signature_jpg():
    img = Image.new("RGB", (600, 200), "white")
    ImageDraw.Draw(img).line([(20, 150), (200, 40), (380, 160), (580, 60)], fill=(10, 20, 120), width=8)
    buf = BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def enable_mfa(user):
    secret = totp.generate_secret()
    user.mfa_secret_encrypted = security.encrypt_secret(secret)
    user.mfa_confirmed_at = timezone.now()
    user.save()
    return secret


def code(secret, offset=0):
    return totp.code_at(secret, totp.time_step() + offset)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class SigningTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="S", name_th="กลุ่มงานลงนาม")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE], first_name_th="ผู้บริหาร", last_name_th="ทดสอบ")
        self.secret = enable_mfa(self.exe)
        pdf = real_pdf()
        self.doc = register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": "ทดสอบลงนาม", "source_doc_no": "x", "source_org": "y", "owner_department": self.dept},
            main_file=("หนังสือ.pdf", pdf, 2), extra_files=[], user=self.clerk,
        )
        self.main = self.doc.main_attachment

    def upload(self):
        return services.upload_signature_image(self.exe, signature_jpg())

    def sign(self, **overrides):
        kwargs = dict(attachment=self.main, user=self.exe, otp_code=code(self.secret),
                      signature={"page": 2, "x": 0.6, "y": 0.7, "w": 0.25})
        kwargs.update(overrides)
        new_file = services.create_final_copy(**kwargs)
        return DocumentSignature.objects.get(signed_attachment=new_file)

    def final_url(self):
        return reverse("signatures:final_copy", args=[self.main.pk])

    def test_upload_replaces_previous_image(self):
        first = self.upload()
        second = self.upload()
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        png = services.read_signature_png(second)
        self.assertEqual(Image.open(BytesIO(png)).mode, "RGBA")

    def test_sign_creates_new_version_and_keeps_original(self):
        self.upload()
        record = self.sign()
        self.assertEqual(record.sig_type, SignatureType.IMAGE)
        self.assertTrue(record.mfa_verified)
        signed = record.signed_attachment
        self.assertTrue(signed.is_signed_copy)
        self.assertEqual(signed.version, 2)
        self.assertEqual(record.source_sha256, self.main.sha256)
        data = storage.read_decrypted(signed.storage_key, signed.sha256)
        self.assertEqual(len(PdfReader(BytesIO(data)).pages), 2)
        self.assertNotEqual(signed.sha256, self.main.sha256)
        self.assertTrue(Attachment.objects.filter(pk=self.main.pk).exists())  # ต้นฉบับยังอยู่
        self.assertTrue(self.doc.events.filter(action=DocumentEvent.Action.SIGNED).exists())

    @override_settings(ESARABAN_SIGN_REQUIRE_OTP=True)
    def test_wrong_or_reused_code_rejected(self):
        self.upload()
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.sign(otp_code="000000")
        good = code(self.secret)
        self.sign(otp_code=good)
        with self.assertRaises(ValidationError):
            self.sign(otp_code=good)  # รหัสเดิมใช้ซ้ำไม่ได้
        self.assertEqual(DocumentSignature.objects.count(), 1)

    def test_requires_signature_image(self):
        from django.core.exceptions import ValidationError

        with self.assertRaisesMessage(ValidationError, "ภาพลายมือชื่อ"):
            self.sign()

    def test_staff_cannot_sign(self):
        from django.core.exceptions import PermissionDenied

        staff = make_user("staff", roles=[RoleCode.STAFF], department=self.dept)
        SignatureImage.objects.create(user=staff, storage_key="x/none.bin", sha256="0", width=1, height=1)
        with self.assertRaises(PermissionDenied):
            self.sign(user=staff)

    def test_head_of_other_department_cannot_sign(self):
        other = Department.objects.create(code="O", name_th="อื่น")
        head = make_user("head_o", roles=[(RoleCode.HEAD, other)])
        self.assertFalse(services.can_sign(head, self.doc))

    def test_secret_document_needs_clearance(self):
        self.doc.secrecy = SecrecyLevel.CONFIDENTIAL
        self.doc.save()
        self.assertFalse(services.can_sign(self.exe, self.doc))

    def test_sign_page_through_web(self):
        self.upload()
        login_verified(self.client, self.exe)
        detail = self.client.get(reverse("documents:detail", args=[self.doc.pk]))
        self.assertContains(detail, "เลือกตำแหน่งบนเอกสารและลงนาม")
        self.assertContains(detail, "ไม่ใช่ Digital Signature")
        viewer = self.client.get(reverse("documents:viewer", args=[self.main.pk]) + "?sign=1")
        self.assertContains(viewer, "วางลายเซ็น")
        self.assertContains(viewer, 'data-start-sign="1"')
        response = self.client.post(self.final_url(), {
            "page": "1", "x": "0.55", "y": "0.70", "w": "0.25",
            "code": code(self.secret),
        })
        record = DocumentSignature.objects.get()
        self.assertRedirects(response, reverse("documents:viewer", args=[record.signed_attachment.pk]))
        self.assertEqual(record.page, 1)
        self.assertIn("x=0.550", record.position)

    def test_size_and_position_validated(self):
        self.upload()
        login_verified(self.client, self.exe)
        for bad in [{"x": "1.5"}, {"w": "0.9"}, {"y": "-0.1"}]:
            data = {"page": "1", "x": "0.5", "y": "0.5", "w": "0.25",
                    "code": code(self.secret)}
            data.update(bad)
            self.client.post(self.final_url(), data)
        self.assertFalse(DocumentSignature.objects.exists())

    def test_viewer_without_sign_right_has_no_sign_tools(self):
        staff = make_user("staff2", roles=[RoleCode.STAFF], department=self.dept)
        login_verified(self.client, staff)
        viewer = self.client.get(reverse("documents:viewer", args=[self.main.pk]))
        self.assertNotContains(viewer, "วางลายเซ็น")

    def test_sign_without_code_when_otp_not_required(self):
        """ค่าเริ่มต้น: ลงนามได้โดยไม่ต้องกรอกรหัส 6 หลัก (ยังต้องเข้าสู่ระบบด้วย MFA)"""
        self.upload()
        login_verified(self.client, self.exe)
        viewer = self.client.get(reverse("documents:viewer", args=[self.main.pk]))
        self.assertNotContains(viewer, 'data-role="code-box"')
        self.client.post(self.final_url(), {"page": "1", "x": "0.5", "y": "0.5", "w": "0.25"})
        self.assertEqual(DocumentSignature.objects.count(), 1)

    @override_settings(ESARABAN_SIGN_REQUIRE_OTP=True)
    def test_sign_without_code_or_with_partial_position_rejected(self):
        self.upload()
        login_verified(self.client, self.exe)
        viewer = self.client.get(reverse("documents:viewer", args=[self.main.pk]))
        self.assertContains(viewer, 'data-role="code-box"')
        self.client.post(self.final_url(), {"page": "1", "x": "0.5", "y": "0.5", "w": "0.25", "code": ""})
        self.client.post(self.final_url(), {"page": "1", "x": "0.5", "code": code(self.secret)})
        self.assertFalse(DocumentSignature.objects.exists())
        self.assertEqual(self.doc.attachments.count(), 1)

    def test_nothing_to_save_creates_no_file(self):
        login_verified(self.client, self.exe)
        response = self.client.post(self.final_url(), {})
        self.assertRedirects(response, reverse("documents:viewer", args=[self.main.pk]), fetch_redirect_response=False)
        self.assertEqual(self.doc.attachments.count(), 1)

    def test_endorse_and_sign_together_make_one_file(self):
        from apps.annotations.models import Annotation

        self.upload()
        Annotation.objects.create(attachment=self.main, kind=Annotation.Kind.TEXT, page=1, x=0.1, y=0.1,
                                  content="ทราบ ดำเนินการ", color="red", size="L", author=self.exe)
        login_verified(self.client, self.exe)
        self.client.post(self.final_url(), {"page": "1", "x": "0.55", "y": "0.70", "w": "0.25",
                                            "code": code(self.secret)})
        new_files = self.doc.attachments.exclude(pk=self.main.pk)
        self.assertEqual(new_files.count(), 1)  # ไฟล์เดียวรวมทั้งสั่งการ/เกษียนและลายเซ็น
        new_file = new_files.get()
        self.assertEqual(new_file.original_name, "หนังสือ (สั่งการ-เกษียน, ลงนาม ผู้บริหาร ทดสอบ).pdf")
        self.assertTrue(new_file.is_signed_copy)
        self.assertEqual(DocumentSignature.objects.get().signed_attachment, new_file)
        actions = set(self.doc.events.values_list("action", flat=True))
        self.assertTrue({DocumentEvent.Action.SIGNED, DocumentEvent.Action.ENDORSED} <= actions)

    def test_page_out_of_range_rejected_by_form(self):
        self.upload()
        login_verified(self.client, self.exe)
        self.client.post(self.final_url(), {
            "page": "9", "x": "0.5", "y": "0.5", "w": "0.25",
            "code": code(self.secret),
        })
        self.assertFalse(DocumentSignature.objects.exists())


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class SignatureUploadPageTests(TestCase):
    def setUp(self):
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE])
        login_verified(self.client, self.exe)

    def test_upload_and_view_own_image(self):
        response = self.client.post(
            reverse("signatures:my_signature"),
            {"image": SimpleUploadedFile("sig.jpg", signature_jpg(), content_type="image/jpeg")},
        )
        self.assertRedirects(response, reverse("signatures:my_signature"))
        image = self.client.get(reverse("signatures:my_signature_image"))
        self.assertEqual(image["Content-Type"], "image/png")

    def test_non_image_rejected(self):
        response = self.client.post(
            reverse("signatures:my_signature"),
            {"image": SimpleUploadedFile("sig.png", b"not an image", content_type="image/png")},
        )
        self.assertContains(response, "ไม่ใช่ไฟล์ภาพที่ถูกต้อง")
        self.assertFalse(SignatureImage.objects.exists())

    def test_staff_has_no_signature_page(self):
        self.client.logout()
        login_verified(self.client, make_user("staff", roles=[RoleCode.STAFF]))
        self.assertEqual(self.client.get(reverse("signatures:my_signature")).status_code, 403)


# ---------------------------------------------------------------- ลายมือชื่อดิจิทัล (ขั้นตอนที่ 7C-2)
from django.test import SimpleTestCase  # noqa: E402

from . import pdfsign, pki  # noqa: E402
from .models import SigningCertificate, TestCertificateAuthority  # noqa: E402


def _png(color=(20, 40, 160, 255)):
    image = Image.new("RGBA", (400, 160), (0, 0, 0, 0))
    ImageDraw.Draw(image).line((10, 120, 390, 30), fill=color, width=8)
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


class PdfSignUnitTests(SimpleTestCase):
    """ส่วนลงนาม/ตรวจ PDF ไม่ใช้ฐานข้อมูล"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ca_key, cls.ca = pki.create_ca("สำนักงานทดสอบ")
        cls.k1, cls.c1 = pki.issue_user_certificate(cls.ca_key, cls.ca, common_name="นายหนึ่ง ทดสอบ")
        cls.k2, cls.c2 = pki.issue_user_certificate(cls.ca_key, cls.ca, common_name="นางสอง ทดสอบ")

    def sign(self, pdf, key, cert, page=1):
        return pdfsign.sign_pdf(pdf, key=key, cert=cert, chain=[self.ca], signer_name=pki.common_name(cert),
                                appearance={"page": page, "x": 0.5, "y": 0.6, "w": 0.25, "png": _png()})

    def test_two_signers_both_valid(self):
        original = real_pdf()
        first = self.sign(original, self.k1, self.c1)
        self.assertTrue(first.startswith(original))  # ต่อท้ายไฟล์ ไม่แก้ไบต์เดิม
        second = self.sign(first, self.k2, self.c2, page=2)
        checks = pdfsign.verify_pdf(second, [self.ca])
        self.assertEqual([c.signer for c in checks], ["นายหนึ่ง ทดสอบ", "นางสอง ทดสอบ"])
        self.assertTrue(all(c.ok for c in checks))
        self.assertEqual([c.covers_whole_file for c in checks], [False, True])
        self.assertEqual(len(PdfReader(BytesIO(second)).pages), 2)

    def test_tampering_and_untrusted_ca_detected(self):
        signed = bytearray(self.sign(real_pdf(), self.k1, self.c1))
        at = signed.find(b"Test page 1")
        signed[at] = ord("X")
        check = pdfsign.verify_pdf(bytes(signed), [self.ca])[0]
        self.assertFalse(check.intact)
        self.assertFalse(check.ok)
        _, other = pki.create_ca("อื่น")
        check = pdfsign.verify_pdf(self.sign(real_pdf(), self.k1, self.c1), [other])[0]
        self.assertTrue(check.intact and check.signature_valid)
        self.assertFalse(check.trusted)

    def test_rotated_page_widget_inside_page(self):
        from pypdf import PdfWriter

        writer = PdfWriter(clone_from=PdfReader(BytesIO(real_pdf(1))))
        writer.pages[0].rotate(90)
        out = BytesIO()
        writer.write(out)
        signed = self.sign(out.getvalue(), self.k1, self.c1)
        page = PdfReader(BytesIO(signed)).pages[0]
        widget = page["/Annots"][0].get_object()
        x0, y0, x1, y1 = (float(v) for v in widget["/Rect"])
        self.assertTrue(0 <= x0 < x1 <= float(page.mediabox.width) and 0 <= y0 < y1 <= float(page.mediabox.height))
        self.assertTrue(pdfsign.verify_pdf(signed, [self.ca])[0].ok)

    def test_thai_names_fit_certificate_limits(self):
        _, cert = pki.issue_user_certificate(self.ca_key, self.ca, common_name="นาย" + "ทดสอบ" * 30)
        self.assertLessEqual(len(pki.common_name(cert).encode()), 64)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class DigitalSigningFlowTests(TestCase):
    def setUp(self):
        SigningTests.setUp(self)
        services.upload_signature_image(self.exe, signature_jpg())
        self.head = make_user("head", roles=[(RoleCode.HEAD, self.dept)], first_name_th="หัวหน้า", last_name_th="ทดสอบ")
        self.head_secret = enable_mfa(self.head)
        services.upload_signature_image(self.head, signature_jpg())

    def post_digital(self, user, secret, attachment, offset=0, **extra):
        login_verified(self.client, user)
        data = {"page": "1", "x": "0.55", "y": "0.6", "w": "0.25", "code": code(secret, offset), "sig_kind": "digital"}
        data.update(extra)
        response = self.client.post(reverse("signatures:final_copy", args=[attachment.pk]), data)
        self.client.logout()
        return response

    def latest(self):
        return self.doc.attachments.order_by("-version").first()

    def test_digital_sign_creates_verified_file_and_certificate(self):
        main = self.doc.main_attachment
        self.post_digital(self.exe, self.secret, main)
        signed = self.latest()
        self.assertNotEqual(signed.pk, main.pk)
        self.assertIn("ลงนามดิจิทัล", signed.original_name)
        record = DocumentSignature.objects.get(signed_attachment=signed)
        self.assertEqual(record.sig_type, SignatureType.DIGITAL)
        self.assertIsNotNone(record.certificate)
        self.assertEqual(TestCertificateAuthority.objects.count(), 1)
        pdf = storage.read_decrypted(signed.storage_key, signed.sha256)
        from .digital import verify_bytes

        checks = verify_bytes(pdf)
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0].ok)
        self.assertEqual(checks[0].signer, "ผู้บริหาร ทดสอบ")
        login_verified(self.client, self.exe)
        viewer = self.client.get(reverse("documents:viewer", args=[signed.pk]))
        self.assertContains(viewer, "ลายมือชื่อดิจิทัลในไฟล์นี้")
        self.assertContains(viewer, "ถูกต้อง")
        ca = self.client.get(reverse("signatures:test_ca"))
        self.assertTrue(ca.content.startswith(b"-----BEGIN CERTIFICATE-----"))
        self.assertContains(self.client.get(reverse("signatures:my_signature")), record.certificate.common_name)

    def test_second_digital_signer_keeps_first_valid_and_reuses_certificate(self):
        self.post_digital(self.exe, self.secret, self.doc.main_attachment)
        first = self.latest()
        self.post_digital(self.head, self.head_secret, first, y="0.3")
        second = self.latest()
        self.assertNotEqual(first.pk, second.pk)
        first_bytes = storage.read_decrypted(first.storage_key, first.sha256)
        second_bytes = storage.read_decrypted(second.storage_key, second.sha256)
        self.assertTrue(second_bytes.startswith(first_bytes))
        from .digital import verify_bytes

        checks = verify_bytes(second_bytes)
        self.assertEqual([c.ok for c in checks], [True, True])
        self.post_digital(self.exe, self.secret, second, offset=1, y="0.1")
        self.assertEqual(SigningCertificate.objects.filter(user=self.exe).count(), 1)

    def test_signed_file_rejects_image_signature_and_endorsement(self):
        from apps.annotations.models import Annotation

        self.post_digital(self.exe, self.secret, self.doc.main_attachment)
        signed = self.latest()
        self.post_digital(self.head, self.head_secret, signed, sig_kind="image")
        self.assertEqual(self.latest().pk, signed.pk)
        Annotation.objects.create(attachment=signed, kind=Annotation.Kind.TEXT, page=1, x=0.1, y=0.1,
                                  content="ทราบ", color="red", size="M", author=self.head)
        login_verified(self.client, self.head)
        self.client.post(reverse("signatures:final_copy", args=[signed.pk]), {})
        self.assertEqual(self.latest().pk, signed.pk)
        viewer = self.client.get(reverse("documents:viewer", args=[signed.pk]))
        self.assertNotContains(viewer, 'data-action="toggle-text"')  # เกษียนลงเนื้อหาไม่ได้แล้ว

    def test_wrong_code_issues_no_certificate(self):
        self.post_digital(self.exe, self.secret, self.doc.main_attachment, code="000000")
        self.assertFalse(SigningCertificate.objects.exists())
        self.assertEqual(self.doc.attachments.count(), 1)

    @override_settings(ESARABAN_DIGITAL_SIGNING=False)
    def test_digital_can_be_disabled(self):
        self.post_digital(self.exe, self.secret, self.doc.main_attachment)
        self.assertEqual(self.doc.attachments.count(), 1)
        login_verified(self.client, self.exe)
        viewer = self.client.get(reverse("documents:viewer", args=[self.doc.main_attachment.pk]))
        self.assertNotContains(viewer, 'value="digital"')
