import time
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.constants import RoleCode, SecrecyLevel

from . import flow, permissions, security, totp
from .models import BackupCode, Department, LoginAttempt, Role, UserRole
from .testing import PASSWORD, login_verified, make_admin, make_user

User = get_user_model()


def enable_mfa(user):
    """ตั้ง MFA ให้ผู้ใช้ในเทสต์ คืนค่า secret ไว้สร้างรหัส"""
    secret = totp.generate_secret()
    user.mfa_secret_encrypted = security.encrypt_secret(secret)
    user.mfa_confirmed_at = timezone.now()
    user.save()
    return secret


def current_code(secret, offset=0):
    return totp.code_at(secret, totp.time_step() + offset)


# ---------------------------------------------------------------------------
# โมเดล
# ---------------------------------------------------------------------------


class UserModelTests(TestCase):
    def test_custom_user_model_is_active(self):
        self.assertEqual(User._meta.label, "accounts.User")

    def test_primary_key_is_uuid(self):
        self.assertIsInstance(make_user("tester").pk, uuid.UUID)

    def test_display_name_prefers_thai_name(self):
        user = User(username="u1", first_name_th="สมมติ", last_name_th="ทดลองใช้")
        self.assertEqual(user.display_name_th, "สมมติ ทดลองใช้")

    def test_display_name_falls_back_to_username(self):
        self.assertEqual(User(username="u2").display_name_th, "u2")

    def test_clearance_blocks_higher_secrecy(self):
        user = User(username="u3", clearance_level=SecrecyLevel.CONFIDENTIAL)
        self.assertTrue(user.can_view_secrecy(SecrecyLevel.CONFIDENTIAL))
        self.assertFalse(user.can_view_secrecy(SecrecyLevel.SECRET))

    def test_inactive_user_cannot_view_anything(self):
        user = User(username="u4", is_active=False, clearance_level=SecrecyLevel.TOP_SECRET)
        self.assertFalse(user.can_view_secrecy(SecrecyLevel.NORMAL))

    def test_six_roles_seeded(self):
        self.assertEqual(set(Role.objects.values_list("code", flat=True)), set(RoleCode.values))


class DepartmentTests(TestCase):
    def test_code_is_unique(self):
        Department.objects.create(code="D01", name_th="กลุ่มงานทดสอบ")
        with self.assertRaises(IntegrityError):
            Department.objects.create(code="D01", name_th="ซ้ำ")

    def test_cannot_delete_department_with_members(self):
        dept = Department.objects.create(code="D02", name_th="กลุ่มงานทดสอบ 2")
        make_user("member", department=dept)
        with self.assertRaises(ProtectedError):
            dept.delete()


# ---------------------------------------------------------------------------
# TOTP และการเข้ารหัส
# ---------------------------------------------------------------------------


class TOTPTests(TestCase):
    def test_rfc6238_vectors(self):
        key = b"12345678901234567890"
        vectors = {59: "94287082", 1111111109: "07081804", 1234567890: "89005924", 20000000000: "65353130"}
        for t, expected in vectors.items():
            self.assertEqual(totp.hotp(key, t // 30, digits=8), expected)

    def test_secret_is_encrypted_at_rest(self):
        user = make_user("enc")
        secret = enable_mfa(user)
        user.refresh_from_db()
        self.assertNotIn(secret, user.mfa_secret_encrypted)
        self.assertEqual(security.decrypt_secret(user.mfa_secret_encrypted), secret)

    def test_same_code_cannot_be_used_twice(self):
        user = make_user("replay")
        secret = enable_mfa(user)
        code = current_code(secret)
        self.assertTrue(security.verify_user_totp(user, code))
        self.assertFalse(security.verify_user_totp(user, code))

    def test_backup_code_works_once(self):
        user = make_user("backup")
        codes = security.generate_backup_codes(user)
        self.assertEqual(len(codes), 10)
        self.assertTrue(security.use_backup_code(user, codes[0].lower()))  # ไม่สนตัวพิมพ์เล็ก-ใหญ่
        self.assertFalse(security.use_backup_code(user, codes[0]))
        self.assertEqual(security.remaining_backup_codes(user), 9)
        self.assertFalse(BackupCode.objects.filter(code_hash=codes[1]).exists())  # ไม่เก็บรหัสตรง ๆ


# ---------------------------------------------------------------------------
# การเข้าสู่ระบบ 2 ขั้น
# ---------------------------------------------------------------------------


@override_settings(ESARABAN_LOGIN_REQUIRE_MFA=True)
class LoginFlowTests(TestCase):
    def setUp(self):
        self.user = make_user("somchai", roles=[RoleCode.STAFF])
        self.secret = enable_mfa(self.user)

    def _password_step(self, username="somchai", password=PASSWORD, **extra):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": password}, **extra)

    def test_full_login_with_totp(self):
        response = self._password_step()
        self.assertRedirects(response, reverse("accounts:mfa_verify"))
        # ผ่านรหัสผ่านแล้วแต่ยังไม่ถือว่าเข้าสู่ระบบ
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 302)
        response = self.client.post(reverse("accounts:mfa_verify"), {"code": current_code(self.secret)})
        self.assertRedirects(response, reverse("core:home"))
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)
        self.assertTrue(LoginAttempt.objects.filter(username="somchai", success=True).exists())

    def test_wrong_password_gives_generic_error(self):
        response = self._password_step(password="wrong-password")
        self.assertContains(response, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        self.assertTrue(LoginAttempt.objects.filter(username="somchai", success=False).exists())

    def test_wrong_mfa_code_rejected(self):
        self._password_step()
        response = self.client.post(reverse("accounts:mfa_verify"), {"code": "000000"})
        self.assertContains(response, "รหัสยืนยันไม่ถูกต้อง")
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 302)

    def test_lockout_after_five_failures_even_with_correct_password(self):
        for _ in range(5):
            self._password_step(password="wrong-password")
        response = self._password_step()
        self.assertContains(response, "ระงับการเข้าสู่ระบบชั่วคราว")
        self.assertNotIn(flow.PENDING_USER, self.client.session)

    def test_lockout_message_same_for_unknown_username(self):
        for _ in range(5):
            self._password_step(username="nobody", password="x")
        self.assertContains(self._password_step(username="nobody", password="x"), "ระงับการเข้าสู่ระบบชั่วคราว")

    def test_lockout_expires(self):
        for _ in range(5):
            self._password_step(password="wrong-password")
        LoginAttempt.objects.update(created_at=timezone.now() - timedelta(minutes=16))
        self.assertRedirects(self._password_step(), reverse("accounts:mfa_verify"))

    def test_mfa_failures_count_toward_lockout(self):
        self._password_step()
        for _ in range(5):
            response = self.client.post(reverse("accounts:mfa_verify"), {"code": "000000"})
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertContains(self._password_step(), "ระงับการเข้าสู่ระบบชั่วคราว")

    def test_backup_code_login(self):
        codes = security.generate_backup_codes(self.user)
        self._password_step()
        response = self.client.post(reverse("accounts:mfa_verify"), {"code": codes[3]})
        self.assertRedirects(response, reverse("core:home"))

    def test_pending_step_expires(self):
        self._password_step()
        session = self.client.session
        session[flow.PENDING_AT] = int(time.time()) - flow.PENDING_TTL_SECONDS - 5
        session.save()
        response = self.client.post(reverse("accounts:mfa_verify"), {"code": current_code(self.secret)})
        self.assertRedirects(response, reverse("accounts:login"))

    def test_next_parameter_is_followed_but_not_external(self):
        self.client.post(
            reverse("accounts:login") + "?next=/accounts/me/",
            {"username": "somchai", "password": PASSWORD, "next": "/accounts/me/"},
        )
        response = self.client.post(reverse("accounts:mfa_verify"), {"code": current_code(self.secret)})
        self.assertRedirects(response, reverse("accounts:profile"))

        self.client.post(reverse("accounts:logout"))
        self.client.post(reverse("accounts:login"), {"username": "somchai", "password": PASSWORD, "next": "https://evil.example/"})
        response = self.client.post(reverse("accounts:mfa_verify"), {"code": current_code(self.secret, 1)})
        self.assertRedirects(response, reverse("core:home"))

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.assertContains(self._password_step(), "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    def test_logout_requires_post(self):
        login_verified(self.client, self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("accounts:logout")), reverse("accounts:login"))
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 302)


@override_settings(ESARABAN_LOGIN_REQUIRE_MFA=True)
class MFASetupTests(TestCase):
    def test_first_login_requires_mfa_enrolment(self):
        user = make_user("newbie")
        response = self.client.post(reverse("accounts:login"), {"username": "newbie", "password": PASSWORD})
        self.assertRedirects(response, reverse("accounts:mfa_setup"))

        page = self.client.get(reverse("accounts:mfa_setup"))
        self.assertContains(page, "data:image/svg+xml")
        secret = self.client.session[flow.SETUP_SECRET]

        response = self.client.post(reverse("accounts:mfa_setup"), {"code": "000000"})
        self.assertContains(response, "รหัสยืนยันไม่ถูกต้อง")

        response = self.client.post(reverse("accounts:mfa_setup"), {"code": current_code(secret)})
        # ไม่ให้ assertRedirects เปิดหน้าปลายทางเอง เพราะหน้ารหัสสำรองแสดงได้ครั้งเดียว
        self.assertRedirects(response, reverse("accounts:backup_codes"), fetch_redirect_response=False)
        codes_page = self.client.get(reverse("accounts:backup_codes"))
        self.assertEqual(codes_page.status_code, 200)
        self.assertEqual(len(codes_page.context["codes"]), 10)
        # แสดงครั้งเดียว
        self.assertRedirects(self.client.get(reverse("accounts:backup_codes")), reverse("accounts:profile"))

        user.refresh_from_db()
        self.assertTrue(user.mfa_enabled)

    def test_setup_page_needs_password_step_first(self):
        self.assertRedirects(self.client.get(reverse("accounts:mfa_setup")), reverse("accounts:login"))


class RegenerateBackupCodesTests(TestCase):
    """ผ่านหน้าเว็บจริง (request.user เป็น SimpleLazyObject) จุดที่เคยพบข้อบกพร่อง"""

    def test_regenerate_through_web(self):
        user = make_user("regen")
        secret = enable_mfa(user)
        old = security.generate_backup_codes(user)
        login_verified(self.client, user)
        response = self.client.post(reverse("accounts:regenerate_backup_codes"), {"code": current_code(secret)})
        self.assertRedirects(response, reverse("accounts:backup_codes"), fetch_redirect_response=False)
        self.assertFalse(security.use_backup_code(user, old[0]))  # ชุดเดิมใช้ไม่ได้แล้ว


@override_settings(ESARABAN_LOGIN_REQUIRE_MFA=False)
class PasswordOnlyLoginTests(TestCase):
    """ปิด MFA: ใส่ชื่อผู้ใช้และรหัสผ่านถูกแล้วเข้าระบบได้ทันที ไม่มีหน้ารหัส 6 หลัก"""

    def test_password_logs_in_directly(self):
        make_user("direct", roles=[RoleCode.STAFF])
        response = self.client.post(reverse("accounts:login"), {"username": "direct", "password": PASSWORD})
        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)
        self.assertNotContains(self.client.get(reverse("accounts:login"), follow=True), "ขั้นที่ 1 จาก 2")

    def test_wrong_password_still_rejected_and_locks_out(self):
        make_user("direct2")
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "direct2", "password": "wrong"})
        response = self.client.post(reverse("accounts:login"), {"username": "direct2", "password": PASSWORD})
        self.assertContains(response, "ระงับการเข้าสู่ระบบชั่วคราว")
        self.assertNotIn("_auth_user_id", self.client.session)


class SessionGuardTests(TestCase):
    def test_session_without_mfa_flag_is_logged_out(self):
        self.client.force_login(make_user("bypass"))
        response = self.client.get(reverse("core:home"))
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_django_admin_login_is_disabled(self):
        response = self.client.get("/admin/login/?next=/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:login")))

    def test_forced_password_change(self):
        user = make_user("temp", must_change_password=True)
        login_verified(self.client, user)
        self.assertRedirects(self.client.get(reverse("core:home")), reverse("accounts:password_change"))
        response = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": PASSWORD, "new_password1": "Brand-New-Passw0rd", "new_password2": "Brand-New-Passw0rd"},
        )
        self.assertRedirects(response, reverse("core:home"))
        user.refresh_from_db()
        self.assertFalse(user.must_change_password)
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)  # ยังอยู่ในระบบ


# ---------------------------------------------------------------------------
# สิทธิ์
# ---------------------------------------------------------------------------


class PermissionTests(TestCase):
    def setUp(self):
        self.parent = Department.objects.create(code="P", name_th="กลุ่มงานแม่")
        self.child = Department.objects.create(code="C", name_th="กลุ่มงานย่อย", parent=self.parent)
        self.other = Department.objects.create(code="O", name_th="กลุ่มงานอื่น")

    def test_scoped_role_covers_child_but_not_sibling(self):
        head = make_user("head", roles=[(RoleCode.HEAD, self.parent)])
        self.assertTrue(permissions.has_capability(head, "review_documents", self.parent))
        self.assertTrue(permissions.has_capability(head, "review_documents", self.child))
        self.assertFalse(permissions.has_capability(head, "review_documents", self.other))

    def test_org_wide_role_covers_everything(self):
        exe = make_user("exe", roles=[RoleCode.EXECUTIVE])
        self.assertTrue(permissions.has_capability(exe, "command_documents", self.other))

    def test_expired_role_has_no_effect(self):
        user = make_user("old")
        UserRole.objects.create(
            user=user,
            role=Role.objects.get(code=RoleCode.CLERK),
            valid_from=timezone.localdate() - timedelta(days=10),
            valid_to=timezone.localdate() - timedelta(days=1),
        )
        self.assertFalse(permissions.has_capability(user, "register_documents"))

    def test_superuser_is_admin_but_not_document_roles(self):
        su = make_user("su", is_superuser=True)
        self.assertTrue(permissions.has_capability(su, "manage_users"))
        self.assertFalse(permissions.has_capability(su, "register_documents"))

    def test_unknown_capability_raises(self):
        with self.assertRaises(ValueError):
            permissions.has_capability(make_user("x"), "fly")

    def test_duplicate_org_wide_role_blocked_by_database(self):
        user = make_user("dup", roles=[RoleCode.STAFF])
        with self.assertRaises(IntegrityError):
            UserRole.objects.create(user=user, role=Role.objects.get(code=RoleCode.STAFF))


# ---------------------------------------------------------------------------
# หน้าจัดการผู้ใช้
# ---------------------------------------------------------------------------


@override_settings(LOGIN_MAX_FAILURES_PER_IP=1000)
class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        login_verified(self.client, self.admin)

    def test_non_admin_gets_403(self):
        self.client.logout()
        login_verified(self.client, make_user("staff", roles=[RoleCode.STAFF]))
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)

    def test_list_and_search(self):
        make_user("findme", first_name_th="ค้นหา")
        make_user("zz-not-matching", first_name_th="ไม่เกี่ยว")
        response = self.client.get(reverse("accounts:user_list"), {"q": "ค้นหา"})
        self.assertContains(response, "findme")
        self.assertNotContains(response, "zz-not-matching")

    def test_create_user_requires_password_change(self):
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "username": "newstaff",
                "first_name_th": "ใหม่",
                "last_name_th": "ทดสอบ",
                "position": "นักทดสอบ",
                "email": "",
                "department": "",
                "clearance_level": "0",
                "password1": "Temp-Passw0rd-123",
                "password2": "Temp-Passw0rd-123",
            },
        )
        user = User.objects.get(username="newstaff")
        self.assertRedirects(response, reverse("accounts:user_detail", args=[user.pk]))
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password("Temp-Passw0rd-123"))

    def test_weak_password_rejected(self):
        response = self.client.post(
            reverse("accounts:user_create"),
            {"username": "weak", "first_name_th": "ก", "last_name_th": "ข", "clearance_level": "0",
             "password1": "12345678", "password2": "12345678"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_add_and_remove_role(self):
        target = make_user("target")
        dept = Department.objects.create(code="D9", name_th="กลุ่มงาน 9")
        clerk = Role.objects.get(code=RoleCode.CLERK)
        self.client.post(
            reverse("accounts:user_role_add", args=[target.pk]),
            {"role-role": clerk.pk, "role-department": dept.pk, "role-valid_from": timezone.localdate().isoformat()},
        )
        assignment = UserRole.objects.get(user=target)
        self.assertEqual(assignment.granted_by, self.admin)
        self.client.post(reverse("accounts:user_role_remove", args=[target.pk, assignment.pk]))
        self.assertFalse(UserRole.objects.filter(user=target).exists())

    def test_cannot_remove_last_admin(self):
        assignment = UserRole.objects.get(user=self.admin, role__code=RoleCode.ADMIN)
        self.client.post(reverse("accounts:user_role_remove", args=[self.admin.pk, assignment.pk]))
        self.assertTrue(UserRole.objects.filter(pk=assignment.pk).exists())

    def test_cannot_deactivate_self(self):
        self.client.post(reverse("accounts:user_toggle_active", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_reset_mfa_and_deactivate_other_user(self):
        target = make_user("phone-lost")
        enable_mfa(target)
        security.generate_backup_codes(target)
        self.client.post(reverse("accounts:user_reset_mfa", args=[target.pk]))
        self.client.post(reverse("accounts:user_toggle_active", args=[target.pk]))
        target.refresh_from_db()
        self.assertFalse(target.mfa_enabled)
        self.assertEqual(target.backup_codes.count(), 0)
        self.assertFalse(target.is_active)

    def test_set_temporary_password(self):
        target = make_user("forgot")
        self.client.post(
            reverse("accounts:user_set_password", args=[target.pk]),
            {"pw-password1": "Another-Temp-999", "pw-password2": "Another-Temp-999"},
        )
        target.refresh_from_db()
        self.assertTrue(target.check_password("Another-Temp-999"))
        self.assertTrue(target.must_change_password)

    def _edit_payload(self, user, **overrides):
        data = {
            "edit-username": user.username, "edit-first_name_th": user.first_name_th,
            "edit-last_name_th": user.last_name_th, "edit-position": "", "edit-email": "",
            "edit-department": "", "edit-clearance_level": str(SecrecyLevel.SECRET),
        }
        data.update(overrides)
        return data

    def test_edit_without_thai_name_shows_clear_error(self):
        # ผู้ใช้ที่สร้างด้วย createsuperuser ไม่มีชื่อภาษาไทย (ปัญหาที่พบจริงในการทดลองใช้)
        target = make_user("noname")
        response = self.client.post(reverse("accounts:user_detail", args=[target.pk]), self._edit_payload(target))
        self.assertContains(response, "ยังไม่ได้บันทึก")
        self.assertContains(response, "has-error")
        target.refresh_from_db()
        self.assertEqual(target.clearance_level, SecrecyLevel.NORMAL)

    def test_edit_saves_clearance(self):
        target = make_user("named", first_name_th="ทดสอบ", last_name_th="ระบบ")
        response = self.client.post(reverse("accounts:user_detail", args=[target.pk]), self._edit_payload(target))
        self.assertRedirects(response, reverse("accounts:user_detail", args=[target.pk]))
        target.refresh_from_db()
        self.assertEqual(target.clearance_level, SecrecyLevel.SECRET)

    def test_department_create_and_no_cycles(self):
        self.client.post(reverse("accounts:department_create"), {"code": "A", "name_th": "กลุ่ม A", "is_active": "on"})
        a = Department.objects.get(code="A")
        b = Department.objects.create(code="B", name_th="กลุ่ม B", parent=a)
        response = self.client.post(
            reverse("accounts:department_edit", args=[a.pk]),
            {"code": "A", "name_th": "กลุ่ม A", "parent": b.pk, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 200)  # ฟอร์มไม่ผ่าน เพราะจะเกิดสังกัดวนซ้ำ
        a.refresh_from_db()
        self.assertIsNone(a.parent)
