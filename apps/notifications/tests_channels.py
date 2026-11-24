"""แจ้งเตือนนอกระบบ: อีเมล LINE และหนังสือเข้าใหม่ (ไม่เชื่อมต่อบริการจริง)"""
import base64
import hashlib
import hmac
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_user
from apps.core.constants import RoleCode, SecrecyLevel, Urgency
from apps.documents.services import register_incoming
from apps.registry.models import RegisterBook

from . import channels, linking
from .models import ContactSetting, Notification
from .services import notify

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-channels-"))
PDF = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"
LINE = dict(LINE_CHANNEL_ACCESS_TOKEN="token", LINE_CHANNEL_SECRET="secret", LINE_OA_ID="@esaraban")
SMTP = dict(NOTIFY_EMAIL_BACKEND="smtp", EMAIL_HOST_USER="office@example.com", EMAIL_HOST_PASSWORD="x",
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE, NOTIFY_ASYNC=False, ESARABAN_SITE_URL="https://es.example",
                   **LINE, **SMTP)
class ChannelTestBase(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="A", name_th="กลุ่มงาน A")
        self.other = Department.objects.create(code="B", name_th="กลุ่มงาน B")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK], clearance_level=SecrecyLevel.SECRET)
        self.head = make_user("head", roles=[(RoleCode.HEAD, self.dept)], clearance_level=SecrecyLevel.SECRET,
                              email="head@example.com")
        self.head_b = make_user("head_b", roles=[(RoleCode.HEAD, self.other)], email="headb@example.com")
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE], clearance_level=SecrecyLevel.SECRET)
        self.staff = make_user("staff", roles=[RoleCode.STAFF], department=self.dept)
        patcher = mock.patch.object(channels, "_post_json")
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def register(self, **data):
        fields = {"subject": "ขอเชิญประชุมคณะทำงาน", "source_doc_no": "x", "source_org": "สำนักงานจังหวัด",
                  "owner_department": self.dept, **data}
        with self.captureOnCommitCallbacks(execute=True):
            return register_incoming(book=RegisterBook.objects.get(code="RCV"), data=fields,
                                     main_file=("main.pdf", PDF, 1), extra_files=[], user=self.clerk)

    def line_texts(self, user_id="U1"):
        return [c.args[1]["messages"][0]["text"] for c in self.post.call_args_list
                if c.args[0] == channels.LINE_PUSH_URL and c.args[1]["to"] == user_id]


class IncomingNotificationTests(ChannelTestBase):
    def test_head_of_owner_department_and_executive_are_told(self):
        doc = self.register(urgency=Urgency.URGENT)
        told = set(Notification.objects.filter(document=doc).values_list("user__username", flat=True))
        self.assertEqual(told, {"head", "exe"})
        self.assertEqual(Notification.objects.get(user=self.head).title, "หนังสือเข้าใหม่ (ด่วน)")

    @override_settings(ESARABAN_NOTIFY_INCOMING_ROLES="")
    def test_can_be_turned_off(self):
        self.assertFalse(Notification.objects.filter(document=self.register()).exists())


class DeliveryTests(ChannelTestBase):
    def test_email_and_line_sent_to_those_who_opted_in(self):
        ContactSetting.objects.create(user=self.head, email_enabled=True, line_user_id="U1", line_enabled=True)
        ContactSetting.objects.create(user=self.exe, email_enabled=False)
        self.register()
        self.assertEqual([m.to for m in mail.outbox], [["head@example.com"]])
        self.assertIn("ขอเชิญประชุมคณะทำงาน", mail.outbox[0].body)
        self.assertIn("https://es.example/documents/", mail.outbox[0].body)
        self.assertEqual(len(self.line_texts("U1")), 1)
        self.assertIn("หนังสือเข้าใหม่", self.line_texts("U1")[0])

    def test_secret_subject_never_leaves_the_system(self):
        ContactSetting.objects.create(user=self.head, email_enabled=True, line_user_id="U1", line_enabled=True)
        self.register(subject="เรื่องลับมากเฉพาะ", secrecy=SecrecyLevel.SECRET)
        self.assertNotIn("เรื่องลับมากเฉพาะ", mail.outbox[0].body + mail.outbox[0].subject)
        self.assertNotIn("เรื่องลับมากเฉพาะ", self.line_texts("U1")[0])
        self.assertIn("ชั้นลับมาก", self.line_texts("U1")[0])

    def test_failure_is_recorded_and_does_not_break_registration(self):
        ContactSetting.objects.create(user=self.head, line_user_id="U1", line_enabled=True)
        self.post.side_effect = RuntimeError("HTTP 429: quota")
        doc = self.register()
        self.assertIsNotNone(doc.pk)
        self.assertIn("quota", ContactSetting.objects.get(user=self.head).last_error)

    def test_brevo_backend_posts_to_api(self):
        ContactSetting.objects.create(user=self.head, email_enabled=True)
        with override_settings(NOTIFY_EMAIL_BACKEND="brevo", BREVO_API_KEY="k", NOTIFY_EMAIL_FROM="es@example.com"):
            self.register()
        call = next(c for c in self.post.call_args_list if c.args[0] == channels.BREVO_URL)
        self.assertEqual(call.args[1]["to"], [{"email": "head@example.com"}])
        self.assertEqual(call.args[2]["api-key"], "k")

    @override_settings(NOTIFY_EMAIL_BACKEND="none", LINE_CHANNEL_ACCESS_TOKEN="")
    def test_nothing_sent_when_not_configured(self):
        ContactSetting.objects.create(user=self.head, email_enabled=True, line_user_id="U1", line_enabled=True)
        self.register()
        self.assertEqual(mail.outbox, [])
        self.post.assert_not_called()

    def test_rolled_back_work_sends_nothing(self):
        ContactSetting.objects.create(user=self.head, email_enabled=True)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify([self.head], "ทดสอบ")
        self.assertEqual(len(callbacks), 1)  # ส่งเมื่อ commit เท่านั้น
        self.assertEqual(mail.outbox, [])


def signed(body):
    digest = hmac.new(b"secret", body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class LineLinkTests(ChannelTestBase):
    url = reverse("notifications:line_webhook")

    def webhook(self, events, signature=None):
        body = json.dumps({"events": events}).encode()
        return self.client.post(self.url, body, content_type="application/json",
                                HTTP_X_LINE_SIGNATURE=signature if signature is not None else signed(body))

    def message(self, text, user_id="U9", source_type="user"):
        return {"type": "message", "replyToken": "r", "source": {"type": source_type, "userId": user_id},
                "message": {"type": "text", "text": text}}

    def test_link_with_code_through_pages(self):
        login_verified(self.client, self.staff)
        self.client.post(reverse("notifications:settings"), {"action": "line_code"})
        page = self.client.get(reverse("notifications:settings"))
        code = page.context["link_code"]
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertIn("oaMessage/%40esaraban/", page.context["line_send_url"])
        self.assertEqual(self.webhook([self.message(f"รหัส {code.lower()}")]).status_code, 200)
        setting = ContactSetting.objects.get(user=self.staff)
        self.assertEqual((setting.line_user_id, setting.line_enabled, setting.link_code_hash), ("U9", True, ""))
        reply = next(c for c in self.post.call_args_list if c.args[0] == channels.LINE_REPLY_URL)
        self.assertIn("เชื่อมกับบัญชี", reply.args[1]["messages"][0]["text"])
        # รหัสใช้ได้ครั้งเดียว
        self.webhook([self.message(code, user_id="U-other")])
        self.assertEqual(ContactSetting.objects.get(user=self.staff).line_user_id, "U9")

    def test_bad_signature_rejected(self):
        code = linking.new_link_code(self.staff)
        self.assertEqual(self.webhook([self.message(code)], signature="bad").status_code, 403)
        self.assertEqual(ContactSetting.objects.get(user=self.staff).line_user_id, "")

    def test_group_chat_and_wrong_code_do_not_link(self):
        code = linking.new_link_code(self.staff)
        self.webhook([self.message(code, source_type="group"), self.message("ABCD-EFGH")])
        self.assertEqual(ContactSetting.objects.get(user=self.staff).line_user_id, "")

    def test_expired_code(self):
        code = linking.new_link_code(self.staff)
        ContactSetting.objects.filter(user=self.staff).update(link_code_expires="2000-01-01T00:00:00Z")
        self.webhook([self.message(code)])
        self.assertEqual(ContactSetting.objects.get(user=self.staff).line_user_id, "")

    @override_settings(LINE_CHANNEL_SECRET="")
    def test_webhook_off_when_not_configured(self):
        self.assertEqual(self.webhook([]).status_code, 404)

    def test_unlink_and_email_settings(self):
        ContactSetting.objects.create(user=self.staff, line_user_id="U9", line_enabled=True)
        login_verified(self.client, self.staff)
        self.client.post(reverse("notifications:settings"), {"action": "line_unlink"})
        self.assertEqual(ContactSetting.objects.get(user=self.staff).line_user_id, "")
        self.client.post(reverse("notifications:settings"),
                         {"action": "email", "email": "staff@example.com", "email_enabled": "1"})
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.email, "staff@example.com")
        self.assertTrue(ContactSetting.objects.get(user=self.staff).email_enabled)
        self.client.post(reverse("notifications:settings"), {"action": "test"})
        self.assertEqual(mail.outbox[-1].to, ["staff@example.com"])

    @override_settings(NOTIFY_EMAIL_BACKEND="none", LINE_CHANNEL_ACCESS_TOKEN="")
    def test_page_explains_when_admin_has_not_set_up(self):
        login_verified(self.client, self.staff)
        page = self.client.get(reverse("notifications:settings"))
        self.assertContains(page, "ผู้ดูแลระบบยังไม่ได้ตั้งค่าการส่งอีเมล")
        self.assertNotContains(page, 'value="line_code"')
