import datetime as dt
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_user
from apps.core.constants import RoleCode
from apps.documents.models import DocumentEvent, DocumentStatus
from apps.documents.services import register_incoming
from apps.registry.models import RegisterBook

from . import services
from .models import ArchiveFolder, ArchiveRecord

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-archive-"))
PDF = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class ArchiveTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="A", name_th="กลุ่มงาน A")
        self.other = Department.objects.create(code="B", name_th="กลุ่มงาน B")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.staff = make_user("staff", roles=[RoleCode.STAFF], department=self.dept)
        self.outsider = make_user("outsider", roles=[RoleCode.STAFF], department=self.other)
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE])
        self.doc = self.register("เรื่องที่จะจัดเก็บ")

    def register(self, subject):
        return register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": subject, "source_doc_no": "x", "source_org": "y", "owner_department": self.dept},
            main_file=("main.pdf", PDF, 1), extra_files=[], user=self.clerk,
        )

    def post_archive(self, user, doc=None, **extra):
        login_verified(self.client, user)
        folder = extra.pop("folder", "2569/ทดสอบ")
        if ArchiveFolder.objects.filter(name=folder).exists():
            data = {"folder": folder}
        else:
            data = {"folder": "__new__", "new_folder": folder}
        data.update({"retention_years": "10", "note": ""}, **extra)
        return self.client.post(reverse("archive:archive", args=[(doc or self.doc).pk]), data)

    def test_clerk_archives_and_document_becomes_read_only(self):
        self.post_archive(self.clerk)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DocumentStatus.ARCHIVED)
        record = ArchiveRecord.objects.get()
        self.assertEqual(record.keep_until, dt.date(timezone.localdate().year + 10, 12, 31))
        self.assertTrue(self.doc.events.filter(action=DocumentEvent.Action.ARCHIVED).exists())
        from apps.annotations.services import can_endorse
        from apps.documents import access
        from apps.signatures.services import can_sign

        self.assertFalse(can_sign(self.exe, self.doc))
        self.assertFalse(can_endorse(self.exe, self.doc))
        self.assertFalse(access.can_edit(self.clerk, self.doc))
        detail = self.client.get(reverse("documents:detail", args=[self.doc.pk]))
        self.assertContains(detail, "จัดเก็บแล้ว")
        self.assertContains(detail, "นำออกจากคลัง")

    def test_new_folder_becomes_a_choice_next_time(self):
        self.post_archive(self.clerk, folder="  2569/ร้องเรียน  ")
        self.assertEqual(list(ArchiveFolder.objects.values_list("name", flat=True)), ["2569/ร้องเรียน"])
        other = self.register("เรื่องที่สอง")
        page = self.client.get(reverse("documents:detail", args=[other.pk]))
        self.assertContains(page, '<option value="2569/ร้องเรียน">2569/ร้องเรียน</option>', html=True)
        self.client.post(reverse("archive:archive", args=[other.pk]),
                         {"folder": "2569/ร้องเรียน", "retention_years": "10"})
        self.assertEqual(ArchiveRecord.objects.filter(folder="2569/ร้องเรียน").count(), 2)
        self.assertEqual(ArchiveFolder.objects.count(), 1)

    def test_new_folder_needs_a_name(self):
        login_verified(self.client, self.clerk)
        self.client.post(reverse("archive:archive", args=[self.doc.pk]),
                         {"folder": "__new__", "new_folder": "  ", "retention_years": "10"})
        self.assertFalse(ArchiveRecord.objects.exists())

    def test_permanent_retention_has_no_end_date(self):
        self.post_archive(self.clerk, retention_years="0")
        self.assertIsNone(ArchiveRecord.objects.get().keep_until)

    def test_staff_and_running_workflow_cannot_archive(self):
        self.post_archive(self.staff)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DocumentStatus.REGISTERED)
        from apps.workflow.models import WorkflowTemplate
        from apps.workflow.services import start_workflow

        head = make_user("head", roles=[(RoleCode.HEAD, self.dept)])
        self.assertTrue(head.pk)
        start_workflow(self.doc, WorkflowTemplate.objects.get(name="มาตรฐาน: หนังสือรับทั่วไป"), self.clerk)
        self.doc.refresh_from_db()
        self.assertFalse(services.can_archive(self.clerk, self.doc))
        self.assertFalse(ArchiveRecord.objects.exists())

    def test_release_requires_reason_and_restores_status(self):
        self.post_archive(self.clerk)
        url = reverse("archive:release", args=[self.doc.pk])
        self.client.post(url, {"reason": ""})
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DocumentStatus.ARCHIVED)
        self.client.post(url, {"reason": "ต้องดำเนินการต่อ"})
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.status, DocumentStatus.REGISTERED)
        record = ArchiveRecord.objects.get()
        self.assertEqual(record.release_reason, "ต้องดำเนินการต่อ")
        self.post_archive(self.clerk, folder="แฟ้มใหม่")  # จัดเก็บซ้ำได้ ประวัติเดิมยังอยู่
        self.assertEqual(ArchiveRecord.objects.count(), 2)

    def test_archive_list_respects_visibility_and_due_filter(self):
        self.post_archive(self.clerk)
        login_verified(self.client, self.staff)
        self.assertContains(self.client.get(reverse("archive:index")), "เรื่องที่จะจัดเก็บ")
        login_verified(self.client, self.outsider)
        self.assertNotContains(self.client.get(reverse("archive:index")), "เรื่องที่จะจัดเก็บ")
        ArchiveRecord.objects.update(keep_until=timezone.localdate() - dt.timedelta(days=1))
        login_verified(self.client, self.clerk)
        page = self.client.get(reverse("archive:index"), {"due": "1"})
        self.assertContains(page, "ครบอายุ")
        self.assertContains(page, "เรื่องที่จะจัดเก็บ")
