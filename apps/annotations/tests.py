import json
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_user
from apps.core.constants import RoleCode
from apps.documents.services import register_incoming
from apps.registry.models import RegisterBook

from .models import Annotation

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-ann-"))
PDF = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class AnnotationTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="N", name_th="กลุ่มงาน N")
        self.other = Department.objects.create(code="M", name_th="กลุ่มงาน M")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.staff = make_user("staff", roles=[RoleCode.STAFF], department=self.dept)
        self.outsider = make_user("outsider", roles=[RoleCode.STAFF], department=self.other)
        doc = register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": "ทดสอบความเห็น", "source_doc_no": "x", "source_org": "y", "owner_department": self.dept},
            main_file=("main.pdf", PDF, 3), extra_files=[], user=self.clerk,
        )
        self.attachment = doc.main_attachment
        self.url = reverse("annotations:list", args=[self.attachment.pk])

    def post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def test_create_list_and_delete_own(self):
        login_verified(self.client, self.staff)
        response = self.post({"page": 2, "x": 0.5, "y": 0.25, "content": "ตรวจตัวเลขย่อหน้านี้"})
        self.assertEqual(response.status_code, 201)
        note_id = response.json()["annotation"]["id"]
        listed = self.client.get(self.url).json()["annotations"]
        self.assertEqual([n["content"] for n in listed], ["ตรวจตัวเลขย่อหน้านี้"])
        self.assertTrue(listed[0]["can_delete"])
        self.client.post(reverse("annotations:delete", args=[note_id]))
        self.assertEqual(self.client.get(self.url).json()["annotations"], [])
        self.assertIsNotNone(Annotation.objects.get(pk=note_id).deleted_at)  # เก็บร่องรอย ไม่ลบจริง

    def test_cannot_delete_others_note(self):
        login_verified(self.client, self.clerk)
        note_id = self.post({"page": 1, "x": 0.1, "y": 0.1, "content": "ของสารบรรณ"}).json()["annotation"]["id"]
        self.client.logout()
        login_verified(self.client, self.staff)
        self.assertEqual(self.client.post(reverse("annotations:delete", args=[note_id])).status_code, 403)

    def test_outsider_gets_404(self):
        login_verified(self.client, self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.post({"page": 1, "x": 0.1, "y": 0.1, "content": "x"}).status_code, 404)

    def test_invalid_input_rejected(self):
        login_verified(self.client, self.staff)
        for payload in [
            {"page": 9, "x": 0.1, "y": 0.1, "content": "หน้าเกิน"},
            {"page": 1, "x": 1.5, "y": 0.1, "content": "นอกหน้า"},
            {"page": 1, "x": 0.1, "y": 0.1, "content": "   "},
            {"page": "abc", "x": 0.1, "y": 0.1, "content": "x"},
            {"page": 1, "x": 0.1, "y": 0.1, "content": "ก" * 2001},
        ]:
            with self.subTest(payload=str(payload)[:40]):
                self.assertEqual(self.post(payload).status_code, 400)
        self.assertFalse(Annotation.objects.exists())

    def test_html_is_stored_as_text(self):
        login_verified(self.client, self.staff)
        self.post({"page": 1, "x": 0.1, "y": 0.1, "content": "<img src=x onerror=alert(1)>"})
        self.assertEqual(self.client.get(self.url).json()["annotations"][0]["content"], "<img src=x onerror=alert(1)>")

    def test_viewer_page_renders(self):
        login_verified(self.client, self.staff)
        response = self.client.get(reverse("documents:viewer", args=[self.attachment.pk]))
        self.assertContains(response, 'id="pdf-app"')
        self.assertContains(response, "js/pdf-viewer.js")


def real_pdf(pages=2):
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    for n in range(pages):
        c.drawString(72, 800, f"Test page {n + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class EndorsementTests(TestCase):
    """สั่งการ/เกษียน: พิมพ์ข้อความลงบนหน้าเอกสาร เลือกสี/ขนาด ลากย้าย และฝังลงไฟล์ฉบับใหม่"""

    def setUp(self):
        self.dept = Department.objects.create(code="N", name_th="กลุ่มงาน N")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.head = make_user("head", roles=[(RoleCode.HEAD, self.dept)], department=self.dept)
        self.staff = make_user("staff", roles=[RoleCode.STAFF], department=self.dept)
        doc = register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": "ทดสอบสั่งการ/เกษียน", "source_doc_no": "x", "source_org": "y", "owner_department": self.dept},
            main_file=("main.pdf", real_pdf(2), 2), extra_files=[], user=self.clerk,
        )
        self.doc = doc
        self.attachment = doc.main_attachment
        self.url = reverse("annotations:list", args=[self.attachment.pk])

    def post_text(self, **extra):
        payload = {"kind": "TEXT", "page": 1, "x": 0.3, "y": 0.2, "content": "ทราบ มอบกลุ่มงานไต่สวน\nดำเนินการ",
                   "color": "red", "size": "L", **extra}
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def test_head_types_text_with_ink(self):
        login_verified(self.client, self.head)
        response = self.post_text()
        self.assertEqual(response.status_code, 201)
        data = response.json()["annotation"]
        self.assertEqual(data["kind"], "TEXT")
        self.assertEqual(data["color"], "#B42318")
        self.assertAlmostEqual(data["size_ratio"], 22 / 595)

    def test_staff_cannot_endorse_but_can_still_pin_notes(self):
        login_verified(self.client, self.staff)
        self.assertEqual(self.post_text().status_code, 403)
        note = self.client.post(self.url, json.dumps({"page": 1, "x": 0.1, "y": 0.1, "content": "ความเห็น"}),
                                content_type="application/json")
        self.assertEqual(note.status_code, 201)
        self.assertEqual(note.json()["annotation"]["kind"], "NOTE")
        viewer = self.client.get(reverse("documents:viewer", args=[self.attachment.pk]))
        self.assertNotContains(viewer, 'data-action="toggle-text"')

    def test_viewer_shows_ink_choices_for_endorser(self):
        login_verified(self.client, self.head)
        viewer = self.client.get(reverse("documents:viewer", args=[self.attachment.pk]))
        self.assertContains(viewer, 'data-action="toggle-text"')
        for color in ("blue", "red", "black", "green"):
            self.assertContains(viewer, f'data-color="{color}"')
        for size in ("S", "M", "L"):
            self.assertContains(viewer, f'data-size="{size}"')

    def test_invalid_color_size_or_kind_rejected(self):
        login_verified(self.client, self.head)
        for extra in [{"color": "pink"}, {"size": "XL"}, {"kind": "IMAGE"}, {"content": "บรรทัด\n" * 40}]:
            with self.subTest(extra=str(extra)[:30]):
                self.assertEqual(self.post_text(**extra).status_code, 400)
        self.assertFalse(Annotation.objects.exists())

    def test_move_own_text_only(self):
        login_verified(self.client, self.head)
        note_id = self.post_text().json()["annotation"]["id"]
        move = reverse("annotations:move", args=[note_id])
        ok = self.client.post(move, json.dumps({"x": 0.5, "y": 0.6}), content_type="application/json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual((ok.json()["annotation"]["x"], ok.json()["annotation"]["y"]), (0.5, 0.6))
        bad = self.client.post(move, json.dumps({"x": 2, "y": 0.6}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        self.client.logout()
        login_verified(self.client, self.clerk)
        other = self.client.post(move, json.dumps({"x": 0.1, "y": 0.1}), content_type="application/json")
        self.assertEqual(other.status_code, 403)

    def test_render_text_produces_png_with_thai_shaping(self):
        from django.conf import settings
        from PIL import features

        from .render import render_text

        self.assertTrue(features.check("raqm"), "ต้องติดตั้ง libfribidi ใน image (ดู Dockerfile)")
        png, width_pt = render_text("ที่ดิน ผู้ใหญ่ น้ำ", color_hex="#1F3A93", font_pt=16,
                                    font_path=settings.ESARABAN_TEXT_FONT)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(width_pt, 50)

    def test_endorse_only_creates_new_version_and_keeps_original(self):
        from io import BytesIO

        from pypdf import PdfReader

        from apps.documents import storage
        from apps.documents.models import DocumentEvent

        login_verified(self.client, self.head)
        self.post_text()
        self.post_text(page=2, color="blue", size="S", content="ทราบ")
        response = self.client.post(reverse("signatures:final_copy", args=[self.attachment.pk]))
        new_file = self.doc.attachments.exclude(pk=self.attachment.pk).get()
        self.assertRedirects(response, reverse("documents:viewer", args=[new_file.pk]), fetch_redirect_response=False)
        self.assertEqual(new_file.original_name, "main (สั่งการ-เกษียน).pdf")
        self.assertFalse(new_file.is_signed_copy)
        self.assertEqual(new_file.version, self.attachment.version + 1)
        reader = PdfReader(BytesIO(storage.read_decrypted(new_file.storage_key, new_file.sha256)))
        self.assertEqual(len(reader.pages), 2)
        for page in reader.pages:
            self.assertIn("/XObject", page["/Resources"])  # มีภาพข้อความฝังอยู่ทั้งสองหน้า
        self.assertTrue(self.doc.events.filter(action=DocumentEvent.Action.ENDORSED).exists())
        original = storage.read_decrypted(self.attachment.storage_key, self.attachment.sha256)
        self.assertNotIn(b"/XObject", original)

    def test_endorse_without_text_or_permission(self):
        login_verified(self.client, self.head)
        response = self.client.post(reverse("signatures:final_copy", args=[self.attachment.pk]))
        self.assertRedirects(response, reverse("documents:viewer", args=[self.attachment.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(self.doc.attachments.count(), 1)
        self.post_text()
        self.client.logout()
        login_verified(self.client, self.staff)
        self.client.post(reverse("signatures:final_copy", args=[self.attachment.pk]))
        self.assertEqual(self.doc.attachments.count(), 1)
