import datetime as dt
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_admin, make_user
from apps.core.constants import RoleCode
from apps.documents.services import register_incoming
from apps.registry.models import RegisterBook
from apps.workflow import services as wf
from apps.workflow.models import TaskStatus, WorkflowTask, WorkflowTemplate

from . import registers, services

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-reports-"))
PDF = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class ReportTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="A", name_th="กลุ่มงานเอ")
        self.other = Department.objects.create(code="B", name_th="กลุ่มงานบี")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.head = make_user("head", roles=[(RoleCode.HEAD, self.dept)], first_name_th="หัวหน้า", last_name_th="เอ")
        self.head_b = make_user("head_b", roles=[(RoleCode.HEAD, self.other)])
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE])
        self.late = self.register("เรื่องค้างนานมาก", self.dept)
        self.fresh = self.register("เรื่องใหม่กลุ่มบี", self.other)
        wf.start_workflow(self.late, WorkflowTemplate.objects.get(name="มาตรฐาน: หนังสือรับทั่วไป"), self.clerk)
        WorkflowTask.objects.filter(status=TaskStatus.OPEN).update(due_at=timezone.now() - dt.timedelta(days=3))

    def register(self, subject, dept):
        return register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": subject, "source_doc_no": "x", "source_org": "หน่วยงานต้นทาง", "owner_department": dept},
            main_file=("main.pdf", PDF, 1), extra_files=[], user=self.clerk,
        )

    def test_executive_dashboard_counts_and_overdue_list(self):
        data = services.dashboard(self.exe)
        self.assertTrue(data["can_list"])
        self.assertEqual(data["kpi"]["received_month"], 2)
        self.assertEqual(data["kpi"]["in_review"], 1)
        self.assertEqual(data["kpi"]["overdue_tasks"], 1)
        row = data["overdue_list"][0]
        self.assertEqual(row["document"], self.late)
        self.assertEqual(row["holder"], "หัวหน้ากลุ่มงาน กลุ่มงานเอ")
        self.assertGreaterEqual(row["late_days"], 2)
        self.assertEqual(sum(m["received"] for m in data["monthly"]), 2)
        login_verified(self.client, self.exe)
        self.assertContains(self.client.get(reverse("reports:dashboard")), "เรื่องค้างนานมาก")

    def test_head_sees_only_own_department(self):
        data = services.dashboard(self.head_b)
        self.assertEqual(data["kpi"]["received_month"], 1)
        self.assertEqual(data["kpi"]["overdue_tasks"], 0)

    def test_admin_sees_totals_without_subjects(self):
        admin = make_admin()
        login_verified(self.client, admin)
        page = self.client.get(reverse("reports:dashboard"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["kpi"]["received_month"], 2)
        self.assertNotContains(page, "เรื่องค้างนานมาก")
        search = self.client.get(reverse("reports:search"), {"q": "เรื่อง"})
        self.assertContains(search, "ไม่ได้รับสิทธิ์อ่านเอกสาร")
        self.assertNotContains(search, "เรื่องค้างนานมาก")

    def test_staff_cannot_open_dashboard(self):
        login_verified(self.client, make_user("staff", roles=[RoleCode.STAFF], department=self.dept))
        self.assertEqual(self.client.get(reverse("reports:dashboard")).status_code, 403)

    def test_search_filters_and_tracking(self):
        login_verified(self.client, self.exe)
        page = self.client.get(reverse("reports:search"), {"q": self.late.registration.display_no})
        self.assertContains(page, "เรื่องค้างนานมาก")
        self.assertNotContains(page, "เรื่องใหม่กลุ่มบี")
        self.assertContains(page, "หัวหน้ากลุ่มงาน กลุ่มงานเอ")  # ตอนนี้อยู่ที่ใคร
        self.assertContains(page, '<span class="es-badge bad">เกินกำหนด</span>')
        overdue = self.client.get(reverse("reports:search"), {"overdue": "on"})
        self.assertContains(overdue, "เรื่องค้างนานมาก")
        self.assertNotContains(overdue, "เรื่องใหม่กลุ่มบี")
        self.client.logout()
        login_verified(self.client, self.head)
        mine = self.client.get(reverse("reports:search"), {"mine": "on"})
        self.assertContains(mine, "เรื่องค้างนานมาก")
        self.assertNotContains(mine, "เรื่องใหม่กลุ่มบี")
        login_verified(self.client, self.head_b)
        self.assertNotContains(self.client.get(reverse("reports:search")), "เรื่องค้างนานมาก")


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class ExportTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="A", name_th="กลุ่มงานเอ")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE])
        self.doc = register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": "หนังสือรับสำหรับรายงาน", "source_doc_no": "ทส 0001/9", "source_org": "หน่วยงานทดสอบ",
                  "owner_department": self.dept},
            main_file=("main.pdf", PDF, 1), extra_files=[], user=self.clerk,
        )
        today = timezone.localdate()
        self.params = {"kind": "incoming", "date_from": today.replace(day=1).isoformat(), "date_to": today.isoformat()}

    def download(self, user, **extra):
        login_verified(self.client, user)
        return self.client.get(reverse("reports:reports"), {**self.params, **extra})

    def test_incoming_register_excel(self):
        from io import BytesIO

        from openpyxl import load_workbook

        response = self.download(self.clerk, format="xlsx")
        self.assertEqual(response.status_code, 200)
        sheet = load_workbook(BytesIO(b"".join(response.streaming_content))).active
        self.assertEqual(sheet["A1"].value, "ทะเบียนหนังสือรับ")
        self.assertEqual(sheet["A5"].value, self.doc.registration.display_no)
        self.assertEqual(sheet["G5"].value, "หนังสือรับสำหรับรายงาน")
        from apps.audit.models import AuditEntry

        self.assertTrue(AuditEntry.objects.filter(action="REPORT_EXPORTED", actor=self.clerk).exists())

    def test_pdf_is_searchable_and_capped(self):
        from io import BytesIO
        from unittest import mock

        from pypdf import PdfReader

        response = self.download(self.exe, format="pdf")
        reader = PdfReader(BytesIO(b"".join(response.streaming_content)))
        self.assertIn("หนังสือรับสำหรับรายงาน", reader.pages[0].extract_text())
        with mock.patch("apps.reports.views.MAX_PDF_ROWS", 0):
            capped = self.download(self.exe, format="pdf")
        self.assertContains(capped, "ดาวน์โหลดเป็น Excel")

    def test_outgoing_register_and_numbers_without_document(self):
        from apps.registry.services import issue_number

        book = RegisterBook.objects.get(code="SND")
        issue_number(book, self.clerk, subject="ขอเลขโดยไม่มีเอกสาร", recipient="ผู้รับทดสอบ")
        clerk_report = registers.outgoing(self.clerk, timezone.localdate(), timezone.localdate())
        self.assertEqual([r[5] for r in clerk_report.rows], ["ขอเลขโดยไม่มีเอกสาร"])
        exe_report = registers.outgoing(self.exe, timezone.localdate(), timezone.localdate())
        self.assertEqual(exe_report.rows, [])  # ผู้บริหารไม่ใช่ผู้ลงทะเบียน ไม่เห็นเลขที่ไม่มีเอกสาร

    def test_pending_report_overdue_only(self):
        make_user("head", roles=[(RoleCode.HEAD, self.dept)])
        wf.start_workflow(self.doc, WorkflowTemplate.objects.get(name="มาตรฐาน: หนังสือรับทั่วไป"), self.clerk)
        today = timezone.localdate()
        self.assertEqual(len(registers.pending(self.exe, today, today).rows), 1)
        self.assertEqual(registers.pending(self.exe, today, today, overdue_only=True).rows, [])
        WorkflowTask.objects.filter(status=TaskStatus.OPEN).update(due_at=timezone.now() - dt.timedelta(days=2))
        row = registers.pending(self.exe, today, today, overdue_only=True).rows[0]
        self.assertEqual(row[3], "หัวหน้ากลุ่มงาน กลุ่มงานเอ")

    def test_staff_cannot_download_reports(self):
        staff = make_user("staff", roles=[RoleCode.STAFF], department=self.dept)
        self.assertEqual(self.download(staff, format="xlsx").status_code, 403)

    def test_auditor_exports_audit_log(self):
        from io import BytesIO

        from openpyxl import load_workbook

        from apps.audit.models import AuditEntry

        auditor = make_user("auditor", roles=[RoleCode.AUDITOR])
        login_verified(self.client, auditor)
        response = self.client.get(reverse("audit:export"), {"category": "REGISTRY"})
        sheet = load_workbook(BytesIO(b"".join(response.streaming_content))).active
        self.assertEqual(sheet["A1"].value, "Audit Log")
        self.assertIn("ออกเลข", sheet["E5"].value)
        self.assertTrue(AuditEntry.objects.filter(action="AUDIT_EXPORTED").exists())


class ExcelInjectionTests(TestCase):
    def test_text_starting_with_equals_stays_text(self):
        import zipfile
        from io import BytesIO

        from .exports import to_xlsx

        data = to_xlsx("t", "s", [("เรื่อง", 1)], [['=HYPERLINK("http://example.invalid","คลิก")']])
        sheet_xml = zipfile.ZipFile(BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
        self.assertNotIn("<f>", sheet_xml)
