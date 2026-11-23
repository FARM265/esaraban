import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw
from pypdf import PdfReader

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_admin, make_user
from apps.core.constants import RoleCode, SecrecyLevel
from apps.documents import storage
from apps.documents.models import DocumentEvent, DocumentStatus
from apps.registry.models import RegisterBook

from . import layout, services, thaibreak
from .models import LetterContent, Letterhead

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-letters-"))
LONG = ("สำนักงานคณะกรรมการป้องกันและปราบปรามการทุจริตแห่งชาติประจำจังหวัดเชียงใหม่ขอความร่วมมือจัดส่งข้อมูลทดสอบ" * 3)


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


def fonts():
    return settings.ESARABAN_TEXT_FONT, settings.ESARABAN_TEXT_FONT_BOLD


def image_count(pdf, page=0):
    resources = PdfReader(BytesIO(pdf)).pages[page]["/Resources"]
    return len(resources.get("/XObject", {}))


class LayoutTests(SimpleTestCase):
    """ส่วนจัดหน้าไม่ใช้ฐานข้อมูล"""

    def spec(self, kind, **extra):
        return layout.LetterSpec(
            kind=kind, org_name="สำนักงานทดสอบ", subject="ทดสอบระบบ", recipient="ผู้อำนวยการ",
            body=["ย่อหน้าแรก " + LONG, "จึงเรียนมาเพื่อโปรดทราบ"], signer_name="นายทดสอบ ระบบงาน",
            signer_position=["ผู้อำนวยการ"], **extra,
        )

    def test_libthai_breaks_thai_words(self):
        self.assertTrue(thaibreak.available(), "ต้องติดตั้ง libthai0 ใน image (ดู Dockerfile)")
        parts = thaibreak.atoms("สำนักงานคณะกรรมการ")
        self.assertEqual("".join(parts), "สำนักงานคณะกรรมการ")
        self.assertGreater(len(parts), 1)

    def test_wrap_keeps_text_and_width(self):
        ts = layout.Typesetter(*fonts())
        lines = ts.wrap(LONG, 14, 300)
        self.assertGreater(len(lines), 2)
        self.assertEqual("".join(lines).replace(" ", ""), LONG.replace(" ", ""))
        self.assertTrue(all(ts.width(line, 14) <= 300.5 for line in lines))

    def test_all_templates_build_with_anchors_and_text_layer(self):
        for kind in layout.KINDS:
            with self.subTest(kind=kind):
                result = layout.build(self.spec(kind), *fonts())
                reader = PdfReader(BytesIO(result.pdf))
                self.assertEqual(len(reader.pages), result.pages)
                self.assertIn("ทดสอบระบบ", reader.pages[0].extract_text())  # ค้นหาข้อความได้
                self.assertIsNotNone(result.date_anchor)
                self.assertIsNotNone(result.sign_anchor)
                self.assertEqual(result.number_anchor is None, kind == "ANNOUNCE")  # ประกาศไม่มีเลขที่บนหนังสือ

    def test_long_body_flows_to_next_page(self):
        spec = self.spec("OUTGOING")
        spec.body = [LONG] * 15
        result = layout.build(spec, *fonts())
        self.assertGreater(result.pages, 1)
        self.assertEqual(result.sign_anchor["page"], result.pages)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class LetterFlowTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="L", name_th="กลุ่มงานทดสอบหนังสือ")
        self.other = Department.objects.create(code="M", name_th="กลุ่มงานอื่น")
        self.staff = make_user("staff", roles=[RoleCode.STAFF], department=self.dept)
        self.outsider = make_user("outsider", roles=[RoleCode.STAFF], department=self.other)
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.head = make_user("head", roles=[(RoleCode.HEAD, self.dept)], department=self.dept)
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE])
        RegisterBook.objects.filter(code="SND").update(org_code="ปช 0019")

    def form_data(self, **extra):
        data = {
            "kind": "OUTGOING", "subject": "ขอความอนุเคราะห์ข้อมูล (ทดสอบ)", "recipient": "ผู้อำนวยการหน่วยงานทดสอบ",
            "body": "ย่อหน้าที่หนึ่ง\nจึงเรียนมาเพื่อโปรดพิจารณา", "closing": "ขอแสดงความนับถือ",
            "signer_name": "นายทดสอบ ระบบงาน", "signer_position": "ผู้อำนวยการ", "owner_department": self.dept.pk,
            "urgency": "0", "secrecy": "0",
        }
        data.update(extra)
        return data

    def create(self, user=None, **extra):
        login_verified(self.client, user or self.staff)
        response = self.client.post(reverse("letters:create"), self.form_data(**extra))
        self.client.logout()
        return response

    def letter_doc(self):
        return LetterContent.objects.select_related("document").get().document

    def test_staff_creates_draft_without_number(self):
        response = self.create()
        doc = self.letter_doc()
        self.assertRedirects(response, reverse("documents:detail", args=[doc.pk]), fetch_redirect_response=False)
        self.assertEqual((doc.kind, doc.status, doc.registration), ("OUTGOING", DocumentStatus.DRAFT, None))
        main = doc.main_attachment
        self.assertTrue(main.original_name.startswith("ร่างหนังสือส่ง"))
        self.assertEqual(main.version, 1)
        self.assertTrue(doc.events.filter(action=DocumentEvent.Action.DRAFTED).exists())
        login_verified(self.client, self.staff)
        detail = self.client.get(reverse("documents:detail", args=[doc.pk]))
        self.assertContains(detail, "แก้ไขร่าง")
        self.assertNotContains(detail, "ออกเลขหนังสือ")  # เจ้าหน้าที่ทั่วไปออกเลขไม่ได้

    def test_validation_by_template(self):
        self.create(recipient="")
        self.assertFalse(LetterContent.objects.exists())
        self.create(kind="ORDER", recipient="ไม่ใช้", reference="ไม่ใช้")
        doc = self.letter_doc()
        self.assertEqual((doc.kind, doc.recipient, doc.letter.reference), ("ORDER", "", ""))

    def test_cannot_choose_secrecy_above_clearance(self):
        self.create(secrecy=str(SecrecyLevel.CONFIDENTIAL))
        self.assertFalse(LetterContent.objects.exists())

    def test_revise_creates_new_draft_version(self):
        self.create()
        doc = self.letter_doc()
        login_verified(self.client, self.staff)
        self.client.post(reverse("letters:revise", args=[doc.pk]), self.form_data(subject="เรื่องที่แก้แล้ว", kind="ORDER"))
        doc.refresh_from_db()
        self.assertEqual(doc.subject, "เรื่องที่แก้แล้ว")
        self.assertEqual(doc.kind, "OUTGOING")  # เปลี่ยนแม่แบบหลังสร้างไม่ได้
        self.assertEqual(doc.main_attachment.version, 2)
        self.assertEqual(doc.attachments.count(), 2)  # ฉบับเดิมยังอยู่
        self.client.logout()
        login_verified(self.client, self.outsider)
        self.assertEqual(self.client.get(reverse("letters:revise", args=[doc.pk])).status_code, 404)

    def test_clerk_issues_number_and_stamps_latest_file(self):
        self.create()
        doc = self.letter_doc()
        draft = doc.main_attachment
        login_verified(self.client, self.clerk)
        self.client.post(reverse("letters:issue", args=[doc.pk]), {"book": RegisterBook.objects.get(code="SND").pk})
        doc.refresh_from_db()
        self.assertEqual(doc.registration.display_no, "ปช 0019/1")
        self.assertEqual(doc.status, DocumentStatus.REGISTERED)
        issued = doc.main_attachment
        self.assertEqual(issued.version, 2)
        self.assertIn("ปช 0019-1", issued.original_name)
        self.assertIsNotNone(doc.letter.letter_date)
        before = storage.read_decrypted(draft.storage_key, draft.sha256)
        after = storage.read_decrypted(issued.storage_key, issued.sha256)
        self.assertEqual(image_count(after), image_count(before) + 2)  # เลขที่ + วันที่
        self.assertTrue(doc.events.filter(action=DocumentEvent.Action.NUMBER_ISSUED).exists())
        # ออกเลขซ้ำหรือแก้ร่างหลังออกเลขไม่ได้
        self.client.post(reverse("letters:issue", args=[doc.pk]), {"book": RegisterBook.objects.get(code="SND").pk})
        self.assertEqual(RegisterBook.objects.get(code="SND").issued_numbers.count(), 1)
        self.assertFalse(services.can_revise(self.staff, doc))

    def test_issue_uses_endorsed_or_signed_copy(self):
        from apps.annotations.models import Annotation
        from apps.signatures.services import create_final_copy

        self.create()
        doc = self.letter_doc()
        Annotation.objects.create(attachment=doc.main_attachment, kind=Annotation.Kind.TEXT, page=1, x=0.1, y=0.05,
                                  content="ชอบ", color="blue", size="M", author=self.head)
        endorsed = create_final_copy(attachment=doc.main_attachment, user=self.head)
        services.issue_number(document=doc, book=RegisterBook.objects.get(code="SND"), user=self.clerk)
        doc.refresh_from_db()
        issued = doc.main_attachment
        self.assertEqual(issued.version, endorsed.version + 1)
        data = storage.read_decrypted(issued.storage_key, issued.sha256)
        before = storage.read_decrypted(endorsed.storage_key, endorsed.sha256)
        self.assertEqual(image_count(data), image_count(before) + 2)

    def test_cannot_issue_after_digital_signature(self):
        from django.core.exceptions import ValidationError

        from apps.signatures.services import create_final_copy, upload_signature_image
        from apps.signatures.tests import code, enable_mfa, signature_jpg

        self.create()
        doc = self.letter_doc()
        secret = enable_mfa(self.exe)
        upload_signature_image(self.exe, signature_jpg())
        create_final_copy(attachment=doc.main_attachment, user=self.exe, otp_code=code(secret),
                          signature={"page": 1, "x": 0.5, "y": 0.6, "w": 0.25, "digital": True})
        with self.assertRaises(ValidationError):
            services.issue_number(document=doc, book=RegisterBook.objects.get(code="SND"), user=self.clerk)
        doc.refresh_from_db()
        self.assertIsNone(doc.registration)
        self.assertFalse(RegisterBook.objects.get(code="SND").issued_numbers.exists())  # เลขไม่ถูกใช้ไป

    def test_word_download_before_and_after_number(self):
        from io import BytesIO

        from docx import Document as Docx

        self.create()
        doc = self.letter_doc()
        login_verified(self.client, self.staff)
        response = self.client.get(reverse("letters:docx", args=[doc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.filename.startswith("หนังสือส่ง ร่าง - "))
        text = "\n".join(p.text for p in Docx(BytesIO(b"".join(response.streaming_content))).paragraphs)
        self.assertIn("ย่อหน้าที่หนึ่ง", text)
        self.assertIn("(นายทดสอบ ระบบงาน)", text)
        self.assertTrue(doc.events.filter(action=DocumentEvent.Action.DOWNLOADED, detail__file=response.filename).exists())
        services.issue_number(document=doc, book=RegisterBook.objects.get(code="SND"), user=self.clerk)
        issued = Docx(BytesIO(b"".join(self.client.get(reverse("letters:docx", args=[doc.pk])).streaming_content)))
        table_text = issued.tables[0].rows[0].cells[0].text
        self.assertEqual(table_text, "ที่ ปช 0019/1")
        self.client.logout()
        login_verified(self.client, self.outsider)
        self.assertEqual(self.client.get(reverse("letters:docx", args=[doc.pk])).status_code, 404)

    def test_staff_cannot_issue(self):
        self.create()
        doc = self.letter_doc()
        login_verified(self.client, self.staff)
        self.client.post(reverse("letters:issue", args=[doc.pk]), {"book": RegisterBook.objects.get(code="SND").pk})
        doc.refresh_from_db()
        self.assertIsNone(doc.registration)

    def test_announcement_has_no_number_on_paper(self):
        self.create(kind="ANNOUNCE")
        doc = self.letter_doc()
        number = services.issue_number(document=doc, book=RegisterBook.objects.get(code="ANN"), user=self.clerk)
        self.assertTrue(number.display_no)
        doc.refresh_from_db()
        draft = doc.attachments.get(version=1)
        data = storage.read_decrypted(doc.main_attachment.storage_key, doc.main_attachment.sha256)
        before = storage.read_decrypted(draft.storage_key, draft.sha256)
        self.assertEqual(image_count(data, -1), image_count(before, -1) + 1)  # วันที่อย่างเดียว

    def test_wrong_register_book_rejected(self):
        from django.core.exceptions import ValidationError

        self.create()
        doc = self.letter_doc()
        with self.assertRaises(ValidationError):
            services.issue_number(document=doc, book=RegisterBook.objects.get(code="RCV"), user=self.clerk)
        doc.refresh_from_db()
        self.assertIsNone(doc.registration)
        self.assertFalse(RegisterBook.objects.get(code="RCV").issued_numbers.exists())

    def test_author_proposes_draft_and_cancel_returns_to_draft(self):
        from apps.workflow import services as wf
        from apps.workflow.models import Decision, WorkflowTemplate
        from apps.workflow.panel import can_start

        self.create()
        doc = self.letter_doc()
        self.assertTrue(can_start(self.staff, doc))
        template = WorkflowTemplate.objects.get(doc_kind="OUTGOING")
        instance = wf.start_workflow(doc, template, self.staff)
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.IN_REVIEW)
        self.assertFalse(services.can_revise(self.staff, doc))
        self.assertFalse(services.can_issue(self.clerk, doc))
        wf.act(instance.tasks.get(status="OPEN"), self.head, Decision.RETURN, comment="แก้ย่อหน้าที่สอง")
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.RETURNED)
        self.assertTrue(services.can_revise(self.staff, doc))  # ถูกส่งกลับแก้ไข จึงแก้ร่างได้
        wf.act(instance.tasks.get(status="OPEN"), self.staff, Decision.CANCEL, comment="ไม่ส่งแล้ว")
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.DRAFT)

    def test_viewer_preplaces_signature_for_signer(self):
        self.create()
        doc = self.letter_doc()
        login_verified(self.client, self.exe)
        viewer = self.client.get(reverse("documents:viewer", args=[doc.main_attachment.pk]))
        self.assertRegex(viewer.content.decode(), r'data-sign-default="1,0\.\d+,0\.\d+,0\.25"')


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class LetterheadTests(TestCase):
    def emblem(self):
        image = Image.new("RGB", (200, 220), "white")
        ImageDraw.Draw(image).ellipse((20, 20, 180, 200), outline=(0, 0, 0), width=10)
        out = BytesIO()
        image.save(out, "PNG")
        out.name = "emblem.png"
        out.seek(0)
        return out

    def test_admin_updates_letterhead_and_emblem(self):
        admin = make_admin()
        login_verified(self.client, admin)
        response = self.client.post(reverse("letters:letterhead"), {
            "org_name": "สำนักงานทดสอบหัวหนังสือ", "address": "บรรทัด 1\nบรรทัด 2", "default_contact": "", "emblem": self.emblem(),
        })
        self.assertRedirects(response, reverse("letters:letterhead"))
        head = Letterhead.current()
        self.assertEqual(head.address_lines, ["บรรทัด 1", "บรรทัด 2"])
        png = services.emblem_png(head)
        self.assertEqual(Image.open(BytesIO(png)).mode, "RGBA")
        self.assertEqual(self.client.get(reverse("letters:emblem")).status_code, 200)

    def test_non_admin_cannot_change_letterhead(self):
        login_verified(self.client, make_user("staff", roles=[RoleCode.STAFF]))
        self.assertEqual(self.client.get(reverse("letters:letterhead")).status_code, 403)

    def test_bad_emblem_rejected(self):
        login_verified(self.client, make_admin())
        bad = BytesIO(b"not an image")
        bad.name = "x.png"
        self.client.post(reverse("letters:letterhead"), {"org_name": "x", "address": "", "default_contact": "", "emblem": bad})
        self.assertFalse(Letterhead.current().emblem_key)
