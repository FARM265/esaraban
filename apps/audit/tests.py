import shutil
import tempfile
from pathlib import Path

from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Department
from apps.accounts.testing import PASSWORD, login_verified, make_admin, make_user
from apps.core.constants import RoleCode, SecrecyLevel
from apps.documents.services import register_incoming
from apps.registry.models import RegisterBook

from . import services
from .models import AuditEntry

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-audit-"))
PDF = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


def tampering_allowed():
    """ปิด trigger ชั่วคราวเพื่อจำลองผู้ไม่หวังดีที่เข้าถึงฐานข้อมูลโดยตรง (ย้อนกลับเมื่อจบเทสต์)"""
    with connection.cursor() as cursor:
        # foreign key ของ Django ตรวจตอนจบ transaction ต้องตรวจให้เสร็จก่อน PostgreSQL จึงยอมให้ ALTER TABLE
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("ALTER TABLE audit_auditentry DISABLE TRIGGER audit_entry_no_update")


class ChainTests(TestCase):
    def setUp(self):
        self.user = make_user("u1")
        for i in range(5):
            services.record("SETTINGS", "TEST", f"รายการทดสอบ {i}", actor=self.user, ip="10.0.0.1", n=i, tags=["ก", "ข"])

    def test_chain_links_and_verifies(self):
        entries = list(AuditEntry.objects.order_by("seq"))
        self.assertEqual([e.seq for e in entries][-5:], list(range(entries[-5].seq, entries[-5].seq + 5)))
        for prev, cur in zip(entries, entries[1:]):
            self.assertEqual(cur.prev_hash, prev.hash)
        self.assertTrue(services.verify().ok)

    def test_cannot_edit_or_delete_through_django(self):
        entry = AuditEntry.objects.order_by("seq").last()
        entry.summary = "แก้ไข"
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()

    def test_database_trigger_blocks_update_and_delete(self):
        entry = AuditEntry.objects.order_by("seq").last()
        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditEntry.objects.filter(pk=entry.pk).update(summary="แก้ไขตรงในฐานข้อมูล")
        with self.assertRaises(DatabaseError), transaction.atomic():
            AuditEntry.objects.filter(pk=entry.pk).delete()
        self.assertEqual(AuditEntry.objects.get(pk=entry.pk).summary, "รายการทดสอบ 4")

    def test_verify_detects_modified_middle_and_tail_tampering(self):
        entries = list(AuditEntry.objects.order_by("seq"))
        middle, last = entries[-3], entries[-1]
        tampering_allowed()
        with transaction.atomic():
            sid = transaction.savepoint()
            AuditEntry.objects.filter(pk=middle.pk).update(summary="ถูกแก้")
            result = services.verify()
            self.assertFalse(result.ok)
            self.assertEqual(result.problem_seq, middle.seq)
            transaction.savepoint_rollback(sid)
            sid = transaction.savepoint()
            AuditEntry.objects.filter(pk=middle.pk).delete()
            self.assertEqual(services.verify().problem_seq, middle.seq)
            transaction.savepoint_rollback(sid)
            AuditEntry.objects.filter(pk=last.pk).delete()
            result = services.verify()
            self.assertFalse(result.ok)
            self.assertEqual(result.problem_seq, last.seq)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class CoverageTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="A", name_th="กลุ่มงาน A")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK], clearance_level=SecrecyLevel.SECRET)

    def register(self, secrecy=SecrecyLevel.NORMAL, subject="เรื่องทดสอบ audit"):
        return register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": subject, "source_doc_no": "x", "source_org": "y", "owner_department": self.dept,
                  "secrecy": secrecy},
            main_file=("main.pdf", PDF, 1), extra_files=[], user=self.clerk, ip="10.1.1.1",
        )

    def test_document_and_registry_events_recorded(self):
        doc = self.register()
        actions = list(AuditEntry.objects.filter(target_id__in=[str(doc.pk), str(doc.registration.pk)])
                       .values_list("category", "action"))
        self.assertIn(("REGISTRY", "NUMBER_ISSUED"), actions)
        self.assertIn(("DOCUMENT", "REGISTERED"), actions)
        entry = AuditEntry.objects.get(action="REGISTERED", target_id=str(doc.pk))
        self.assertIn("เรื่องทดสอบ audit", entry.summary)
        self.assertEqual(entry.ip_address, "10.1.1.1")
        self.assertEqual(entry.actor, self.clerk)

    def test_secret_subject_not_exposed_to_auditor(self):
        doc = self.register(secrecy=SecrecyLevel.SECRET, subject="ชื่อเรื่องลับมาก")
        entry = AuditEntry.objects.get(action="REGISTERED", target_id=str(doc.pk))
        self.assertNotIn("ชื่อเรื่องลับมาก", entry.summary)
        self.assertIn("ลับ", entry.summary)

    def test_login_success_and_failure_recorded(self):
        user = make_user("loginuser")
        self.client.post(reverse("accounts:login"), {"username": "loginuser", "password": "wrong-password"})
        self.client.post(reverse("accounts:login"), {"username": "nobody", "password": PASSWORD})
        failed = AuditEntry.objects.filter(action="LOGIN_FAILED")
        self.assertEqual(failed.count(), 2)
        self.assertTrue(all(e.actor is None for e in failed))
        self.assertEqual(set(failed.values_list("actor_label", flat=True)), {"loginuser", "nobody"})
        self.assertTrue(user.pk)

    def test_role_change_recorded(self):
        admin = make_admin()
        target = make_user("target")
        login_verified(self.client, admin)
        from django.utils import timezone

        from apps.accounts.models import Role

        self.client.post(reverse("accounts:user_role_add", args=[target.pk]), {
            "role-role": Role.objects.get(code=RoleCode.STAFF).pk, "role-department": "",
            "role-valid_from": timezone.localdate().isoformat(),
        })
        entry = AuditEntry.objects.get(action="ROLE_GRANTED")
        self.assertEqual(entry.actor, admin)
        self.assertEqual(entry.target_id, str(target.pk))


class AuditPageTests(TestCase):
    def test_auditor_sees_and_verifies(self):
        auditor = make_user("auditor", roles=[RoleCode.AUDITOR])
        services.record("SETTINGS", "TEST", "รายการสำหรับหน้าจอ", actor=auditor)
        login_verified(self.client, auditor)
        page = self.client.get(reverse("audit:index"), {"q": "หน้าจอ"})
        self.assertContains(page, "รายการสำหรับหน้าจอ")
        response = self.client.post(reverse("audit:verify"), follow=True)
        self.assertContains(response, "ครบถ้วน")
        self.assertTrue(AuditEntry.objects.filter(action="AUDIT_VERIFIED").exists())

    def test_staff_cannot_open(self):
        login_verified(self.client, make_user("staff", roles=[RoleCode.STAFF]))
        self.assertEqual(self.client.get(reverse("audit:index")).status_code, 403)
