import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_user
from apps.core.constants import RoleCode, SecrecyLevel
from apps.documents.services import register_incoming
from apps.registry.models import RegisterBook
from apps.workflow import services as wf
from apps.workflow.models import Decision, TaskStatus, WorkflowTemplate

from . import services
from .models import Notification

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-notify-"))
PDF = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class WorkflowNotificationTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="A", name_th="กลุ่มงาน A")
        self.other = Department.objects.create(code="B", name_th="กลุ่มงาน B")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.head = make_user("head", roles=[(RoleCode.HEAD, self.dept)])
        self.head_b = make_user("head_b", roles=[(RoleCode.HEAD, self.other)])
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE])
        self.staff = make_user("staff", roles=[RoleCode.STAFF], department=self.dept)
        self.doc = register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": "เรื่องแจ้งเตือน", "source_doc_no": "x", "source_org": "y", "owner_department": self.dept},
            main_file=("main.pdf", PDF, 1), extra_files=[], user=self.clerk,
        )
        self.instance = wf.start_workflow(self.doc, WorkflowTemplate.objects.get(name="มาตรฐาน: หนังสือรับทั่วไป"),
                                          self.clerk)

    def task(self):
        return self.instance.tasks.get(status=TaskStatus.OPEN)

    def titles(self, user):
        return list(Notification.objects.filter(user=user).values_list("title", flat=True))

    def test_flow_notifies_the_right_people(self):
        self.assertEqual(self.titles(self.head), ["มีเรื่องรอพิจารณา"])
        self.assertEqual(self.titles(self.head_b), [])      # หัวหน้ากลุ่มงานอื่นไม่เกี่ยว
        self.assertEqual(self.titles(self.clerk), [])       # ผู้เสนอเองไม่ต้องแจ้ง
        wf.act(self.task(), self.head, Decision.FORWARD)
        self.assertEqual(self.titles(self.exe), ["มีเรื่องรอสั่งการ/ลงนาม"])
        wf.act(self.task(), self.exe, Decision.COMMAND, command_text="ดำเนินการภายในสัปดาห์นี้", assignees=[self.staff])
        note = Notification.objects.get(user=self.staff)
        self.assertEqual(note.title, "ได้รับมอบหมายให้ดำเนินการ")
        self.assertIn("ดำเนินการภายในสัปดาห์นี้", note.body)
        self.assertEqual(note.url, reverse("documents:detail", args=[self.doc.pk]))
        wf.act(self.task(), self.staff, Decision.COMPLETE)
        self.assertIn("เรื่องที่ท่านเสนอดำเนินการเสร็จสิ้น", self.titles(self.clerk))

    def test_return_notifies_starter_with_reason(self):
        wf.act(self.task(), self.head, Decision.RETURN, comment="แนบเอกสารไม่ครบ")
        note = Notification.objects.get(user=self.clerk)
        self.assertEqual(note.title, "เรื่องถูกส่งกลับแก้ไข")
        self.assertIn("แนบเอกสารไม่ครบ", note.body)

    def test_open_marks_read_and_redirects(self):
        login_verified(self.client, self.head)
        note = Notification.objects.get(user=self.head)
        self.assertContains(self.client.get(reverse("notifications:index")), "มีเรื่องรอพิจารณา")
        home = self.client.get(reverse("core:home"))
        self.assertContains(home, 'class="bell-count"')
        response = self.client.post(reverse("notifications:open", args=[note.pk]))
        self.assertRedirects(response, reverse("documents:detail", args=[self.doc.pk]), fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertTrue(note.is_read)
        self.assertNotContains(self.client.get(reverse("core:home")), 'class="bell-count"')

    def test_cannot_open_someone_elses_notification(self):
        note = Notification.objects.get(user=self.head)
        login_verified(self.client, self.exe)
        self.assertEqual(self.client.post(reverse("notifications:open", args=[note.pk])).status_code, 404)
        note.refresh_from_db()
        self.assertFalse(note.is_read)

    def test_mark_all_read(self):
        services.notify([self.head], "อีกเรื่อง")
        login_verified(self.client, self.head)
        self.client.post(reverse("notifications:read_all"))
        self.assertFalse(Notification.objects.filter(user=self.head, read_at__isnull=True).exists())


class NotifyRulesTests(TestCase):
    def test_no_notification_for_users_who_cannot_see_document(self):
        dept = Department.objects.create(code="S", name_th="กลุ่มงานลับ")
        clerk = make_user("clerk2", roles=[RoleCode.CLERK], clearance_level=SecrecyLevel.SECRET)
        low = make_user("low", roles=[RoleCode.STAFF], department=dept)
        with override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE):
            doc = register_incoming(
                book=RegisterBook.objects.get(code="RCV"),
                data={"subject": "ลับ", "source_doc_no": "x", "source_org": "y", "owner_department": dept,
                      "secrecy": SecrecyLevel.SECRET},
                main_file=("main.pdf", PDF, 1), extra_files=[], user=clerk,
            )
        self.assertEqual(services.notify([low], "ทดสอบ", document=doc), [])
        inactive = make_user("gone", is_active=False)
        self.assertEqual(services.notify([inactive], "ทดสอบ"), [])

    def test_safe_url_blocks_external_redirect(self):
        self.assertEqual(services.safe_url("/documents/"), "/documents/")
        for bad in ("https://evil.example", "//evil.example", "/\\evil"):
            self.assertEqual(services.safe_url(bad), reverse("notifications:index"))
