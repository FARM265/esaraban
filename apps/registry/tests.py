import threading

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.testing import login_verified, make_admin, make_user
from apps.core.constants import RoleCode

from . import services
from .formatting import render_number, validate_number_format
from .models import IssuedNumber, NumberSequence, RegisterBook, RegisterType


def make_book(code="T1", fmt="{org}/{no:04d}", rtype=RegisterType.SEND, **extra):
    return RegisterBook.objects.create(
        code=code, name_th=f"ชุดทดสอบ {code}", register_type=rtype, number_format=fmt, org_code="ปช XXXX", **extra
    )


class FormatTests(TestCase):
    def test_render(self):
        self.assertEqual(render_number("{org}/{no:04d}", "ปช XXXX", 7, 2569), "ปช XXXX/0007")
        self.assertEqual(render_number("{no}/{year}", "", 1524, 2569), "1524/2569")

    def test_rejects_unknown_or_unsafe_fields(self):
        for bad in ["{org}", "{foo}/{no}", "{no.__class__}", "{no[0]}", "{no!r}", "{org:>10}/{no}", "{no"]:
            with self.subTest(fmt=bad), self.assertRaises(ValidationError):
                validate_number_format(bad)

    def test_accepts_valid_formats(self):
        for good in ["{no}", "{org}/{no}", "ที่ {no:03d}/{year}"]:
            validate_number_format(good)

    def test_seeded_books_exist(self):
        self.assertEqual(RegisterBook.objects.filter(code__in=["RCV", "SND", "INT", "ORD", "ANN"]).count(), 5)


class IssueNumberTests(TestCase):
    def setUp(self):
        self.user = make_user("clerk", roles=[RoleCode.CLERK])
        self.book = make_book()

    def test_numbers_are_sequential(self):
        numbers = [services.issue_number(self.book, self.user).display_no for _ in range(3)]
        self.assertEqual(numbers, ["ปช XXXX/0001", "ปช XXXX/0002", "ปช XXXX/0003"])

    def test_each_year_starts_from_one(self):
        services.issue_number(self.book, self.user, year_be=2569)
        services.issue_number(self.book, self.user, year_be=2569)
        self.assertEqual(services.issue_number(self.book, self.user, year_be=2570).running_no, 1)

    def test_books_are_independent(self):
        other = make_book("T2")
        services.issue_number(self.book, self.user)
        self.assertEqual(services.issue_number(other, self.user).running_no, 1)

    def test_inactive_book_cannot_issue(self):
        self.book.is_active = False
        self.book.save()
        with self.assertRaises(ValidationError):
            services.issue_number(self.book, self.user)

    def test_void_keeps_number_and_never_reuses_it(self):
        first = services.issue_number(self.book, self.user)
        services.void_number(first, self.user, "พิมพ์ผิด")
        first.refresh_from_db()
        self.assertTrue(first.is_voided)
        self.assertEqual(first.voided_by, self.user)
        self.assertEqual(services.issue_number(self.book, self.user).running_no, 2)

    def test_void_requires_reason_and_only_once(self):
        number = services.issue_number(self.book, self.user)
        with self.assertRaises(ValidationError):
            services.void_number(number, self.user, "   ")
        services.void_number(number, self.user, "เหตุผล")
        with self.assertRaises(ValidationError):
            services.void_number(number, self.user, "ซ้ำ")

    def test_issued_numbers_cannot_be_deleted(self):
        number = services.issue_number(self.book, self.user)
        with self.assertRaises(ValidationError):
            number.delete()
        with self.assertRaises(ValidationError):
            IssuedNumber.objects.all().delete()
        self.assertTrue(IssuedNumber.objects.filter(pk=number.pk).exists())

    def test_database_rejects_duplicate_number(self):
        number = services.issue_number(self.book, self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IssuedNumber.objects.create(
                book=self.book, year_be=number.year_be, running_no=1, display_no="ซ้ำ", issued_by=self.user
            )

    def test_database_rejects_void_without_reason(self):
        number = services.issue_number(self.book, self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IssuedNumber.objects.filter(pk=number.pk).update(status=IssuedNumber.Status.VOIDED)

    def test_failed_transaction_does_not_consume_number(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            services.issue_number(self.book, self.user)
            raise RuntimeError("ขั้นตอนถัดไปล้มเหลว")
        self.assertEqual(services.issue_number(self.book, self.user).running_no, 1)


class ConcurrentIssueTests(TransactionTestCase):
    """จำลองเจ้าหน้าที่หลายคนกดออกเลขพร้อมกันจริง (แต่ละ thread ใช้ connection ฐานข้อมูลของตัวเอง)"""

    serialized_rollback = True  # คืนข้อมูลที่ migration สร้างไว้ (บทบาท ชุดทะเบียน) หลังเทสต์นี้

    def test_parallel_requests_get_unique_consecutive_numbers(self):
        workers = 8
        user = make_user("parallel", roles=[RoleCode.CLERK])
        book = make_book("PAR")
        barrier = threading.Barrier(workers)
        results, errors = [], []

        def worker():
            try:
                barrier.wait(timeout=10)
                results.append(services.issue_number(book, user).running_no)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), list(range(1, workers + 1)))
        self.assertEqual(NumberSequence.objects.get(book=book).last_number, workers)


class RegistryViewTests(TestCase):
    def setUp(self):
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK])
        self.book = make_book()

    def test_staff_without_registry_role_gets_403(self):
        login_verified(self.client, make_user("staff", roles=[RoleCode.STAFF]))
        self.assertEqual(self.client.get(reverse("registry:index")).status_code, 403)

    def test_clerk_issues_and_voids_number(self):
        login_verified(self.client, self.clerk)
        self.client.post(reverse("registry:issue", args=[self.book.pk]), {"subject": "หนังสือทดสอบ", "recipient": "หน่วยงาน ก"})
        number = IssuedNumber.objects.get(book=self.book)
        self.assertEqual(number.subject, "หนังสือทดสอบ")
        page = self.client.get(reverse("registry:index"), {"book": self.book.pk})
        self.assertContains(page, "ปช XXXX/0001")

        self.client.post(reverse("registry:void", args=[number.pk]), {"reason": ""})
        number.refresh_from_db()
        self.assertFalse(number.is_voided)
        self.client.post(reverse("registry:void", args=[number.pk]), {"reason": "ออกเลขผิดชุด"})
        number.refresh_from_db()
        self.assertTrue(number.is_voided)

    def test_receive_numbers_only_from_registration_page(self):
        login_verified(self.client, self.clerk)
        receive_book = RegisterBook.objects.get(code="RCV")
        self.client.post(reverse("registry:issue", args=[receive_book.pk]), {"subject": "x"})
        self.assertFalse(IssuedNumber.objects.filter(book=receive_book).exists())

    def test_executive_can_view_but_not_issue(self):
        login_verified(self.client, make_user("exe", roles=[RoleCode.EXECUTIVE]))
        self.assertEqual(self.client.get(reverse("registry:index")).status_code, 200)
        self.assertEqual(self.client.post(reverse("registry:issue", args=[self.book.pk]), {"subject": "x"}).status_code, 403)

    def test_admin_edits_book_but_type_locked_after_use(self):
        services.issue_number(self.book, self.clerk)
        login_verified(self.client, make_admin())
        self.client.post(
            reverse("registry:book_edit", args=[self.book.pk]),
            {"code": "CHANGED", "name_th": "ชื่อใหม่", "register_type": RegisterType.ORDER,
             "org_code": "ปช XXXX", "number_format": "{no}/{year}", "department": "", "is_active": "on"},
        )
        self.book.refresh_from_db()
        self.assertEqual(self.book.name_th, "ชื่อใหม่")
        self.assertEqual(self.book.number_format, "{no}/{year}")
        self.assertEqual(self.book.code, "T1")
        self.assertEqual(self.book.register_type, RegisterType.SEND)
