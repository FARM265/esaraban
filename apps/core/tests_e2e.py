"""
ทดสอบทั้งระบบผ่านหน้าเว็บจริง (ขั้นตอนที่ 9)

1. หนังสือรับ: ลงทะเบียน -> เสนอ -> หัวหน้าเสนอต่อ -> ผู้บริหารสั่งการ -> เจ้าหน้าที่ดำเนินการ -> จัดเก็บ
2. หนังสือส่ง: ร่างจากแม่แบบ -> เสนอ -> อนุมัติ -> ออกเลข -> ลงนามดิจิทัล -> Word -> ทะเบียนส่ง -> จัดเก็บ
3. ความปลอดภัย: ทุก URL ต้องเข้าสู่ระบบ, ต้องผ่าน MFA, CSRF, header ความปลอดภัย, สิทธิ์ตามบทบาท, ไฟล์ปลอม
   และการตั้งค่า production ผ่าน check --deploy
"""
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from io import BytesIO, StringIO
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_admin, make_user
from apps.audit import services as audit
from apps.core.constants import RoleCode
from apps.documents.models import Document, DocumentEvent, DocumentStatus
from apps.notifications.models import Notification
from apps.registry.models import RegisterBook
from apps.signatures.tests import code, enable_mfa, real_pdf, signature_jpg
from apps.workflow.models import TaskStatus, WorkflowTask, WorkflowTemplate

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-e2e-"))


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


class Office:
    """บุคลากรสมมติของสำนักงาน (ข้อมูลทดสอบ ไม่ใช่ข้อมูลจริง)"""

    def __init__(self):
        self.dept = Department.objects.create(code="INV", name_th="กลุ่มงานทดสอบไต่สวน")
        self.other = Department.objects.create(code="ADM", name_th="กลุ่มงานทดสอบอำนวยการ")
        self.clerk = make_user("e2e_clerk", roles=[RoleCode.CLERK])
        self.head = make_user("e2e_head", roles=[(RoleCode.HEAD, self.dept)], department=self.dept)
        self.exe = make_user("e2e_exe", roles=[RoleCode.EXECUTIVE], first_name_th="ผู้บริหาร", last_name_th="ทดสอบ")
        self.staff = make_user("e2e_staff", roles=[RoleCode.STAFF], department=self.dept)
        self.outsider = make_user("e2e_outsider", roles=[RoleCode.STAFF], department=self.other)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class EndToEndTests(TestCase):
    def setUp(self):
        self.o = Office()

    def as_user(self, user):
        client = Client()
        login_verified(client, user)
        return client

    def open_task(self, doc):
        return WorkflowTask.objects.get(instance__document=doc, status=TaskStatus.OPEN)

    def act(self, user, doc, decision, **extra):
        response = self.as_user(user).post(
            reverse("workflow:act", args=[self.open_task(doc).pk]), {"decision": decision, **extra}
        )
        self.assertEqual(response.status_code, 302)
        return response

    def test_incoming_letter_full_journey(self):
        o = self.o
        clerk = self.as_user(o.clerk)
        response = clerk.post(reverse("documents:receive"), {
            "book": RegisterBook.objects.get(code="RCV").pk,
            "main_file": SimpleUploadedFile("หนังสือเข้า.pdf", real_pdf(1), content_type="application/pdf"),
            "source_doc_no": "ทส 0001/77", "source_doc_date": timezone.localdate().isoformat(),
            "source_org": "หน่วยงานสมมติ", "subject": "ขอข้อมูลประกอบเรื่องร้องเรียน (ทดสอบ)",
            "recipient": "ผู้อำนวยการ", "urgency": "1", "secrecy": "0", "owner_department": o.dept.pk,
            "due_date": "", "note": "",
        })
        doc = Document.objects.get()
        self.assertRedirects(response, reverse("documents:detail", args=[doc.pk]))

        template = WorkflowTemplate.objects.get(name="มาตรฐาน: หนังสือรับทั่วไป")
        clerk.post(reverse("workflow:start", args=[doc.pk]), {"template": template.pk, "comment": "เสนอเพื่อโปรดพิจารณา"})
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.IN_REVIEW)
        self.assertContains(self.as_user(o.head).get(reverse("workflow:my_tasks")), doc.subject)
        self.assertTrue(Notification.objects.filter(user=o.head, document=doc).exists())

        self.act(o.head, doc, "FORWARD", comment="เห็นควรมอบกลุ่มงานไต่สวน")
        self.act(o.exe, doc, "COMMAND", command_text="มอบดำเนินการภายใน 7 วัน", assignees=[o.staff.pk],
                 due_date=timezone.localdate().isoformat())
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.COMMANDED)
        staff = self.as_user(o.staff)
        self.assertEqual(staff.get(reverse("documents:detail", args=[doc.pk])).status_code, 200)
        self.act(o.staff, doc, "COMPLETE", comment="ส่งข้อมูลแล้ว")
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.DONE)
        self.assertTrue(Notification.objects.filter(user=o.clerk, title__contains="เสร็จสิ้น").exists())

        clerk.post(reverse("archive:archive", args=[doc.pk]), {"folder": "__new__", "new_folder": "2569/ร้องเรียน", "retention_years": "10"})
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.ARCHIVED)
        self.assertContains(clerk.get(reverse("archive:index")), doc.subject)

        actions = list(doc.events.order_by("created_at").values_list("action", flat=True))
        for expected in ("REGISTERED", "WF_STARTED", "WF_FORWARD", "WF_COMMAND", "WF_COMPLETE", "ARCHIVED"):
            self.assertIn(expected, actions)
        self.assertLess(actions.index("WF_COMMAND"), actions.index("WF_COMPLETE"))

        outsider = self.as_user(o.outsider)
        self.assertEqual(outsider.get(reverse("documents:detail", args=[doc.pk])).status_code, 404)
        self.assertEqual(outsider.get(reverse("documents:file", args=[doc.main_attachment.pk])).status_code, 404)
        self.assertNotContains(outsider.get(reverse("reports:search"), {"q": "ร้องเรียน"}), doc.subject)
        self.assertTrue(audit.verify().ok)

    def test_outgoing_letter_full_journey(self):
        from apps.reports import registers
        from apps.signatures.digital import verify_bytes
        from apps.documents import storage

        o = self.o
        staff = self.as_user(o.staff)
        staff.post(reverse("letters:create"), {
            "kind": "OUTGOING", "subject": "ขอเชิญประชุม (ทดสอบ)", "recipient": "ผู้อำนวยการหน่วยงานสมมติ",
            "body": "ด้วยสำนักงานจะจัดประชุม\nจึงเรียนมาเพื่อโปรดทราบ", "closing": "ขอแสดงความนับถือ",
            "signer_name": "ผู้บริหาร ทดสอบ", "signer_position": "ผู้อำนวยการ", "owner_department": o.dept.pk,
            "urgency": "0", "secrecy": "0",
        })
        doc = Document.objects.get()
        self.assertEqual(doc.status, DocumentStatus.DRAFT)
        template = WorkflowTemplate.objects.get(doc_kind="OUTGOING")
        staff.post(reverse("workflow:start", args=[doc.pk]), {"template": template.pk})
        self.act(o.head, doc, "FORWARD")
        self.act(o.exe, doc, "COMMAND", command_text="อนุมัติ ลงนามได้")
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.DONE)

        clerk = self.as_user(o.clerk)
        clerk.post(reverse("letters:issue", args=[doc.pk]), {"book": RegisterBook.objects.get(code="SND").pk})
        doc.refresh_from_db()
        self.assertIsNotNone(doc.registration)
        self.assertTrue(Notification.objects.filter(user=o.staff, title__startswith="ออกเลข").exists())

        secret = enable_mfa(o.exe)
        exe = self.as_user(o.exe)
        exe.post(reverse("signatures:my_signature"),
                 {"image": SimpleUploadedFile("sig.jpg", signature_jpg(), content_type="image/jpeg")})
        exe.post(reverse("signatures:final_copy", args=[doc.main_attachment.pk]), {
            "page": "1", "x": "0.47", "y": "0.62", "w": "0.25", "code": code(secret), "sig_kind": "digital",
        })
        signed = doc.main_attachment
        self.assertIn("ลงนามดิจิทัล", signed.original_name)
        checks = verify_bytes(storage.read_decrypted(signed.storage_key, signed.sha256))
        self.assertEqual([(c.ok, c.signer) for c in checks], [(True, "ผู้บริหาร ทดสอบ")])

        word = staff.get(reverse("letters:docx", args=[doc.pk]))
        from docx import Document as Docx

        self.assertIn(doc.registration.display_no,
                      Docx(BytesIO(b"".join(word.streaming_content))).tables[0].rows[0].cells[0].text)
        today = timezone.localdate()
        rows = registers.outgoing(o.clerk, today, today).rows
        self.assertEqual([r[0] for r in rows], [doc.registration.display_no])

        clerk.post(reverse("archive:archive", args=[doc.pk]), {"folder": "__new__", "new_folder": "2569/หนังสือส่ง", "retention_years": "10"})
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.ARCHIVED)
        self.assertTrue(audit.verify().ok)


PUBLIC_NAMES = {
    "accounts:login", "accounts:mfa_verify", "accounts:mfa_setup", "accounts:logout", "core:healthz",
    "admin_login_redirect", "accounts:backup_codes",
}


def _all_routes(resolver=None, prefix="", namespace=""):
    resolver = resolver or get_resolver()
    for item in resolver.url_patterns:
        if isinstance(item, URLResolver):
            if item.app_name == "admin" or str(item.pattern).startswith("admin"):
                continue
            ns = f"{namespace}{item.namespace}:" if item.namespace else namespace
            yield from _all_routes(item, prefix + str(item.pattern), ns)
        elif isinstance(item, URLPattern):
            yield f"{namespace}{item.name}" if item.name else "", prefix + str(item.pattern)


def _concrete(route):
    import re

    path = re.sub(r"<uuid:\w+>", str(uuid.uuid4()), route)
    path = re.sub(r"<int:\w+>", "1", path)
    path = re.sub(r"<(?:str|slug|path):\w+>", "x", path)
    path = re.sub(r"<\w+>", "x", path)
    return "/" + path.lstrip("^").rstrip("$")


class SecurityTests(TestCase):
    def test_every_page_requires_login(self):
        checked = 0
        for name, route in _all_routes():
            if name in PUBLIC_NAMES or not route or "(?P" in route:
                continue
            response = self.client.get(_concrete(route))
            checked += 1
            with self.subTest(route=route):
                self.assertIn(response.status_code, (302, 404, 405))
                if response.status_code == 302:
                    self.assertTrue(response["Location"].startswith(reverse("accounts:login")), response["Location"])
        self.assertGreater(checked, 40)

    def test_password_without_mfa_is_not_enough(self):
        user = make_user("nomfa", roles=[RoleCode.CLERK])
        self.client.force_login(user)  # ผ่านรหัสผ่านแล้ว แต่ยังไม่ผ่าน MFA
        response = self.client.get(reverse("documents:list"))
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response["Location"], reverse("documents:list"))

    def test_csrf_enforced_on_state_changes(self):
        client = Client(enforce_csrf_checks=True)
        login_verified(client, make_user("csrf", roles=[RoleCode.CLERK]))
        self.assertEqual(client.post(reverse("notifications:read_all")).status_code, 403)

    def test_security_headers(self):
        login_verified(self.client, make_user("hdr"))
        response = self.client.get(reverse("core:home"))
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("camera=()", response["Permissions-Policy"])

    def test_role_matrix(self):
        dept = Department.objects.create(code="M", name_th="กลุ่มงานเมทริกซ์")
        users = {
            "staff": make_user("m_staff", roles=[RoleCode.STAFF], department=dept),
            "clerk": make_user("m_clerk", roles=[RoleCode.CLERK]),
            "auditor": make_user("m_auditor", roles=[RoleCode.AUDITOR]),
            "admin": make_admin("m_admin"),
        }
        expected = {
            "accounts:user_list": {"staff": 403, "clerk": 403, "auditor": 403, "admin": 200},
            "audit:index": {"staff": 403, "clerk": 403, "auditor": 200, "admin": 200},
            "documents:receive": {"staff": 403, "clerk": 200, "auditor": 403, "admin": 403},
            "letters:create": {"staff": 200, "clerk": 200, "auditor": 403, "admin": 403},
            "reports:dashboard": {"staff": 403, "clerk": 403, "auditor": 200, "admin": 200},
            "reports:reports": {"staff": 403, "clerk": 200, "auditor": 200, "admin": 200},
            "letters:letterhead": {"staff": 403, "clerk": 403, "auditor": 403, "admin": 200},
        }
        for name, statuses in expected.items():
            for role, status in statuses.items():
                client = Client()
                login_verified(client, users[role])
                with self.subTest(page=name, role=role):
                    self.assertEqual(client.get(reverse(name)).status_code, status)

    @override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
    def test_disguised_file_rejected(self):
        login_verified(self.client, make_user("up", roles=[RoleCode.CLERK]))
        fake = SimpleUploadedFile("หนังสือ.pdf", b"<html><script>alert(1)</script></html>", content_type="application/pdf")
        self.client.post(reverse("documents:receive"), {
            "book": RegisterBook.objects.get(code="RCV").pk, "main_file": fake, "source_doc_no": "x",
            "source_doc_date": "2026-11-01", "source_org": "y", "subject": "z", "urgency": "0", "secrecy": "0",
        })
        self.assertFalse(Document.objects.exists())

    def test_production_settings_pass_deploy_check(self):
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.prod",
            "SECRET_KEY": "e2e-" + uuid.uuid4().hex + uuid.uuid4().hex,
            "ALLOWED_HOSTS": "esaraban.test",
            "CSRF_TRUSTED_ORIGINS": "https://esaraban.test",
            "DEBUG": "False",
            # ค่าที่ต้องตั้งเมื่อติดตั้งใบรับรองจริงของหน่วยงาน (เครื่องทดลองตั้งเป็น 0 เพราะใช้ใบรับรอง self-signed)
            "SECURE_HSTS_SECONDS": "31536000",
        }
        result = subprocess.run(
            [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "check", "--deploy", "--fail-level", "WARNING"],
            env=env, capture_output=True, text=True, timeout=120, cwd=settings.BASE_DIR,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RestrictedDatabaseRoleTests(TransactionTestCase):
    """ผู้ใช้ฐานข้อมูลแบบจำกัดสิทธิ์ที่ entrypoint สร้างเมื่อตั้ง POSTGRES_APP_USER"""

    serialized_rollback = True
    role = f"esaraban_rt_{uuid.uuid4().hex[:8]}"
    password = "Rt-" + uuid.uuid4().hex

    def tearDown(self):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [self.role])
            if cursor.fetchone():
                cursor.execute(f'DROP OWNED BY "{self.role}"')
                cursor.execute(f'DROP ROLE "{self.role}"')
        super().tearDown()

    def test_app_role_can_use_data_but_not_change_audit_or_schema(self):
        from unittest import mock

        import psycopg
        from django.core.management import call_command
        from django.db import connection

        with mock.patch.dict(os.environ, {"POSTGRES_APP_USER": self.role, "POSTGRES_APP_PASSWORD": self.password}):
            call_command("setup_app_role", stdout=StringIO())
        params = connection.settings_dict
        with psycopg.connect(dbname=params["NAME"], user=self.role, password=self.password,
                             host=params["HOST"], port=params["PORT"], autocommit=True) as conn:
            conn.execute("SELECT count(*) FROM documents_document").fetchone()
            for statement in ("UPDATE audit_auditentry SET summary = summary", "DELETE FROM audit_auditentry",
                              "CREATE TABLE should_fail (x int)", "DELETE FROM django_migrations"):
                with self.subTest(statement=statement), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(statement)
