import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_admin, make_user
from apps.core.constants import RoleCode, SecrecyLevel
from apps.registry.models import IssuedNumber, RegisterBook
from apps.registry.services import current_year_be

from . import access, storage
from .forms import secrecy_choices_for
from .models import Attachment, Document, DocumentEvent, DocumentStatus
from .pdfcheck import PDFRejected, check_pdf

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-test-"))


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


def pdf_bytes(extra=b""):
    """PDF เล็กที่สุดที่ถูกต้อง 1 หน้า (ข้อมูลสมมติ)"""
    return (
        b"%PDF-1.4\n1 0 obj<</Type /Catalog /Pages 2 0 R" + extra + b">>endobj\n"
        b"2 0 obj<</Type /Pages /Kids [3 0 R] /Count 1>>endobj\n"
        b"3 0 obj<</Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )


def pdf_upload(name="หนังสือทดสอบ.pdf", content=None):
    return SimpleUploadedFile(name, content if content is not None else pdf_bytes(), content_type="application/pdf")


class PDFCheckTests(TestCase):
    def test_valid_pdf(self):
        self.assertEqual(check_pdf(pdf_bytes(), 10**6), 1)

    def test_rejections(self):
        cases = {
            "not pdf": b"This is just text",
            "exe prefix": b"MZ\x90\x00" + pdf_bytes(),
            "truncated": pdf_bytes().replace(b"%%EOF", b""),
            "javascript": pdf_bytes(b" /OpenAction<</S /JavaScript /JS (app.alert(1))>>"),
            "launch": pdf_bytes(b" /OpenAction<</S /Launch /F (cmd.exe)>>"),
            "encrypted": pdf_bytes(b" /Encrypt 9 0 R"),
            "empty": b"",
        }
        for name, data in cases.items():
            with self.subTest(case=name), self.assertRaises(PDFRejected):
                check_pdf(data, 10**6)

    def test_size_limit(self):
        with self.assertRaises(PDFRejected):
            check_pdf(pdf_bytes(), 50)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class StorageTests(TestCase):
    def test_file_is_encrypted_on_disk_and_roundtrips(self):
        data = pdf_bytes()
        key, digest = storage.save_encrypted(data)
        raw = (TMP_STORAGE / key).read_bytes()
        self.assertNotIn(b"%PDF", raw)
        self.assertEqual(storage.read_decrypted(key, digest), data)

    def test_hash_mismatch_detected(self):
        key, _ = storage.save_encrypted(pdf_bytes())
        with self.assertRaises(ValueError):
            storage.read_decrypted(key, "0" * 64)

    def test_path_traversal_blocked(self):
        with self.assertRaises(ValueError):
            storage.read_decrypted("../../etc/passwd")


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class ReceiveTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="G1", name_th="กลุ่มงานทดสอบ 1")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK], clearance_level=SecrecyLevel.SECRET)
        self.book = RegisterBook.objects.get(code="RCV")
        login_verified(self.client, self.clerk)

    def post(self, **overrides):
        data = {
            "book": self.book.pk,
            "main_file": pdf_upload(),
            "source_doc_no": "ตย 0000/1234",
            "source_doc_date": "2026-11-18",
            "source_org": "หน่วยงานตัวอย่าง ก",
            "subject": "ขอความร่วมมือส่งข้อมูล (ตัวอย่าง)",
            "recipient": "ผู้อำนวยการ",
            "urgency": "0",
            "secrecy": "0",
            "owner_department": self.dept.pk,
            "due_date": "",
            "note": "",
        }
        data.update(overrides)
        return self.client.post(reverse("documents:receive"), data)

    def test_register_creates_document_number_and_encrypted_file(self):
        response = self.post(extra_files=[pdf_upload("แนบ 1.pdf"), pdf_upload("แนบ 2.pdf")])
        doc = Document.objects.get()
        self.assertRedirects(response, reverse("documents:detail", args=[doc.pk]))
        self.assertEqual(doc.registration.display_no, f"1/{current_year_be()}")
        self.assertEqual(doc.status, DocumentStatus.REGISTERED)
        self.assertEqual(doc.attachments.count(), 3)
        self.assertEqual(doc.main_attachment.original_name, "หนังสือทดสอบ.pdf")
        self.assertTrue(doc.events.filter(action=DocumentEvent.Action.REGISTERED).exists())
        raw = (TMP_STORAGE / doc.main_attachment.storage_key).read_bytes()
        self.assertNotIn(b"%PDF", raw)
        # หน้าเอกสารแสดงไฟล์ล่าสุดทันที (ตัวอย่างโหลดผ่าน URL ที่ตรวจสิทธิ์และบันทึกประวัติ)
        latest = doc.attachments.order_by("-uploaded_at", "-pk").first()
        detail = self.client.get(reverse("documents:detail", args=[doc.pk]))
        self.assertEqual(detail.context["preview"], latest)
        self.assertContains(detail, f'data-file-url="{reverse("documents:file", args=[latest.pk])}"', count=2)

    def test_numbers_continue_across_registrations(self):
        self.post()
        self.post(subject="ฉบับที่สอง")
        self.assertEqual(
            list(Document.objects.order_by("created_at").values_list("registration__running_no", flat=True)), [1, 2]
        )

    def test_fake_pdf_rejected_and_no_number_used(self):
        response = self.post(main_file=pdf_upload("virus.pdf", b"MZ not really a pdf"))
        self.assertContains(response, "ไม่ใช่ไฟล์ PDF จริง")
        self.assertFalse(Document.objects.exists())
        self.assertFalse(IssuedNumber.objects.filter(book=self.book).exists())

    def test_non_pdf_extension_rejected(self):
        response = self.post(main_file=pdf_upload("report.docx"))
        self.assertContains(response, "รับเฉพาะไฟล์ .pdf")

    def test_storage_failure_rolls_back_everything(self):
        with mock.patch.object(storage, "save_encrypted", side_effect=OSError("ดิสก์เต็ม")):
            with self.assertRaises(OSError):
                self.post()
        self.assertFalse(Document.objects.exists())
        self.assertFalse(IssuedNumber.objects.filter(book=self.book).exists())
        self.post()
        self.assertEqual(Document.objects.get().registration.running_no, 1)  # เลขไม่ข้าม

    def test_cannot_choose_secrecy_above_clearance(self):
        low = make_user("lowclerk", roles=[RoleCode.CLERK], clearance_level=SecrecyLevel.NORMAL)
        self.client.logout()
        login_verified(self.client, low)
        response = self.post(secrecy=str(SecrecyLevel.CONFIDENTIAL))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.exists())

    def test_top_secret_disabled_by_default(self):
        top = make_user("top", clearance_level=SecrecyLevel.TOP_SECRET)
        self.assertNotIn(SecrecyLevel.TOP_SECRET, dict(secrecy_choices_for(top)))
        with override_settings(ESARABAN_ALLOW_TOP_SECRET=True):
            self.assertIn(SecrecyLevel.TOP_SECRET, dict(secrecy_choices_for(top)))

    def test_non_clerk_cannot_open_receive_page(self):
        self.client.logout()
        login_verified(self.client, make_user("staff", roles=[RoleCode.STAFF]))
        self.assertEqual(self.client.get(reverse("documents:receive")).status_code, 403)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class AccessTests(TestCase):
    def setUp(self):
        self.dept_a = Department.objects.create(code="A", name_th="กลุ่มงาน A")
        self.dept_a1 = Department.objects.create(code="A1", name_th="กลุ่มงาน A1", parent=self.dept_a)
        self.dept_b = Department.objects.create(code="B", name_th="กลุ่มงาน B")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK], clearance_level=SecrecyLevel.SECRET)
        self.doc = self._make_doc(self.dept_a1)

    def _make_doc(self, dept, secrecy=SecrecyLevel.NORMAL):
        from .services import register_incoming

        return register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": "ทดสอบสิทธิ์", "source_doc_no": "x", "source_org": "y", "secrecy": secrecy,
                  "owner_department": dept},
            main_file=("main.pdf", pdf_bytes(), 1),
            extra_files=[],
            user=self.clerk,
        )

    def assertCanView(self, user, doc, expected):
        self.client.logout()
        login_verified(self.client, user)
        status = self.client.get(reverse("documents:detail", args=[doc.pk])).status_code
        file_status = self.client.get(reverse("documents:file", args=[doc.main_attachment.pk])).status_code
        expected_code = 200 if expected else 404
        self.assertEqual((status, file_status), (expected_code, expected_code), user.username)

    def test_staff_sees_only_own_department(self):
        self.assertCanView(make_user("s-a1", roles=[RoleCode.STAFF], department=self.dept_a1), self.doc, True)
        self.assertCanView(make_user("s-b", roles=[RoleCode.STAFF], department=self.dept_b), self.doc, False)

    def test_head_scope_includes_child_departments(self):
        self.assertCanView(make_user("h-a", roles=[(RoleCode.HEAD, self.dept_a)]), self.doc, True)
        self.assertCanView(make_user("h-b", roles=[(RoleCode.HEAD, self.dept_b)]), self.doc, False)

    def test_secrecy_overrides_role(self):
        secret_doc = self._make_doc(self.dept_a1, SecrecyLevel.SECRET)
        self.assertCanView(make_user("exe-low", roles=[RoleCode.EXECUTIVE]), secret_doc, False)
        self.assertCanView(
            make_user("exe-high", roles=[RoleCode.EXECUTIVE], clearance_level=SecrecyLevel.SECRET), secret_doc, True
        )

    def test_admin_and_auditor_do_not_read_documents(self):
        self.assertCanView(make_admin("sysadmin"), self.doc, False)
        self.assertCanView(make_user("audit", roles=[RoleCode.AUDITOR]), self.doc, False)

    def test_list_shows_only_visible_documents(self):
        other = self._make_doc(self.dept_b)
        staff = make_user("s-a", roles=[RoleCode.STAFF], department=self.dept_a1)
        ids = set(access.visible_documents(staff).values_list("pk", flat=True))
        self.assertEqual(ids, {self.doc.pk})
        login_verified(self.client, staff)
        response = self.client.get(reverse("documents:list"))
        self.assertContains(response, self.doc.registration.display_no)
        self.assertNotContains(response, other.registration.display_no)

    def test_view_and_download_are_logged(self):
        login_verified(self.client, self.clerk)
        url = reverse("documents:file", args=[self.doc.main_attachment.pk])
        response = self.client.get(url)
        self.assertEqual(b"".join(response.streaming_content), pdf_bytes())
        self.assertIn("inline", response["Content-Disposition"])
        response = self.client.get(url, {"download": "1"})
        self.assertIn("attachment", response["Content-Disposition"])
        actions = list(self.doc.events.values_list("action", flat=True))
        self.assertIn(DocumentEvent.Action.VIEWED, actions)
        self.assertIn(DocumentEvent.Action.DOWNLOADED, actions)

    def test_edit_is_logged_and_limited_to_clerk(self):
        staff = make_user("s-a1", roles=[RoleCode.STAFF], department=self.dept_a1)
        login_verified(self.client, staff)
        self.assertEqual(self.client.get(reverse("documents:edit", args=[self.doc.pk])).status_code, 404)

        self.client.logout()
        login_verified(self.client, self.clerk)
        self.client.post(
            reverse("documents:edit", args=[self.doc.pk]),
            {"source_doc_no": "x", "source_doc_date": "2026-11-18", "source_org": "y", "subject": "เรื่องที่แก้แล้ว",
             "recipient": "", "urgency": "2", "secrecy": "0", "owner_department": self.dept_a1.pk,
             "due_date": "", "note": ""},
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.subject, "เรื่องที่แก้แล้ว")
        event = self.doc.events.get(action=DocumentEvent.Action.UPDATED)
        self.assertIn("subject", event.detail["fields"])

    def test_voiding_number_cancels_document(self):
        login_verified(self.client, self.clerk)
        self.client.post(reverse("registry:void", args=[self.doc.registration.pk]), {"reason": "ลงทะเบียนซ้ำ"})
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DocumentStatus.CANCELLED)
        self.assertTrue(self.doc.events.filter(action=DocumentEvent.Action.CANCELLED).exists())
        self.assertTrue(Attachment.objects.filter(document=self.doc).exists())  # ไฟล์ยังอยู่
