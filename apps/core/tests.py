from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.testing import login_verified, make_admin, make_user
from apps.core.constants import RoleCode

from .constants import SecrecyLevel
from .menu import build_menu
from .templatetags.thai_date import thai_date, thai_datetime


class ThaiDateFilterTests(TestCase):
    def test_short_format_uses_buddhist_year(self):
        self.assertEqual(thai_date(date(2026, 11, 20)), "20 พ.ย. 2569")

    def test_full_month_name(self):
        self.assertEqual(thai_date(date(2026, 1, 5), "full"), "5 มกราคม 2569")

    def test_aware_datetime_converted_to_bangkok(self):
        # 23:30 UTC ของวันที่ 31 ธ.ค. คือ 06:30 น. วันที่ 1 ม.ค. ในไทย ปีต้องเปลี่ยนด้วย
        value = datetime(2026, 12, 31, 23, 30, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(thai_datetime(value), "1 ม.ค. 2570 06:30 น.")

    def test_non_date_returns_empty(self):
        self.assertEqual(thai_date("ไม่ใช่วันที่"), "")
        self.assertEqual(thai_date(None), "")


class SecrecyOrderTests(TestCase):
    def test_levels_are_ordered(self):
        self.assertLess(SecrecyLevel.NORMAL, SecrecyLevel.CONFIDENTIAL)
        self.assertLess(SecrecyLevel.SECRET, SecrecyLevel.TOP_SECRET)
        self.assertEqual(SecrecyLevel.TOP_SECRET.label, "ลับที่สุด")


class MenuTests(TestCase):
    def _labels(self, user):
        return [item["label"] for group in build_menu(user) for item in group["items"]]

    def test_unbuilt_modules_are_hidden(self):
        labels = self._labels(make_user("clerk", roles=[RoleCode.CLERK]))
        self.assertIn("ลงทะเบียนรับ", labels)  # พัฒนาแล้วในขั้นตอนที่ 6
        self.assertIn("สร้างหนังสือ", labels)  # พัฒนาแล้วในขั้นตอนที่ 7C
        self.assertNotIn("Audit Log", labels)  # ขั้นตอนที่ 8

    def test_only_most_specific_item_is_active(self):
        groups = build_menu(make_user("clerk2", roles=[RoleCode.CLERK]), "/documents/receive/")
        active = [i["label"] for g in groups for i in g["items"] if i["active"]]
        self.assertEqual(active, ["ลงทะเบียนรับ"])

    def test_every_visible_item_has_working_url(self):
        admin = make_user("super", is_superuser=True, is_staff=True)
        login_verified(self.client, admin)
        for group in build_menu(admin):
            for item in group["items"]:
                response = self.client.get(item["url"])
                self.assertEqual(response.status_code, 200, item["url"])

    def test_staff_without_roles_sees_no_admin_items(self):
        labels = self._labels(make_user("plain"))
        self.assertNotIn("ผู้ใช้และสิทธิ์", labels)
        self.assertNotIn("สถานะระบบ", labels)
        self.assertIn("หน้าหลัก", labels)

    def test_admin_role_sees_user_management(self):
        self.assertIn("ผู้ใช้และสิทธิ์", self._labels(make_admin()))

    @override_settings(DEBUG=False)
    def test_anonymous_sees_nothing(self):
        self.assertEqual(self._labels(AnonymousUser()), [])


class StatusPageTests(TestCase):
    def setUp(self):
        self.url = reverse("core:status")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:login")))

    def test_hidden_from_user_without_admin_role(self):
        login_verified(self.client, make_user("staff1", roles=[RoleCode.STAFF]))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_visible_to_admin_role(self):
        login_verified(self.client, make_admin())
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "เชื่อมต่อ PostgreSQL")
        self.assertContains(response, "ระบบทดลอง")


class HomeTests(TestCase):
    def test_anonymous_redirected_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:login")))

    def test_logged_in_user_sees_home(self):
        login_verified(self.client, make_user("u1", first_name_th="สมมติ", last_name_th="ทดลอง"))
        response = self.client.get("/")
        self.assertContains(response, "สวัสดี สมมติ ทดลอง")


class HealthzTests(TestCase):
    def test_returns_ok_without_login(self):
        response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")


class SecurityHeaderTests(TestCase):
    def test_clickjacking_and_nosniff_headers(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")

    def test_session_cookie_is_httponly(self):
        from django.conf import settings
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 60 * 60)
