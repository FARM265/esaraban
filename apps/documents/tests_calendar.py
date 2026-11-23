"""ลงปฏิทินจากไฟล์: อ่านวันนัดหมาย สร้างลิงก์ Google Calendar และไฟล์ .ics (ข้อมูลสมมติทั้งหมด)"""
from datetime import date, time
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Department
from apps.accounts.testing import login_verified, make_admin, make_user
from apps.audit.models import AuditEntry
from apps.core.constants import RoleCode, SecrecyLevel
from apps.registry.models import RegisterBook

from . import appointment, pdftext
from .services import register_incoming
from .tests import TMP_STORAGE, pdf_bytes, pdf_upload

TODAY = date(2026, 11, 21)

INVITE = """ที่ ปช 0099/123                     สำนักงานทดสอบ
                                        ๑๘ พฤศจิกายน ๒๕๖๙
เรื่อง ขอเชิญประชุมคณะทำงานตรวจสอบข้อเท็จจริง (ทดสอบ)
เรียน ผู้อำนวยการหน่วยงานทดสอบ
อ้างถึง หนังสือหน่วยงานทดสอบ ที่ ทส 0001/123 ลงวันที่ 1 พฤศจิกายน 2569
ด้วยสำนักงานจะจัดประชุมคณะทำงาน ในวันพฤหัสบดีที่ ๒๖ พฤศจิกายน ๒๕๖๙ เวลา ๐๙.๓๐ - ๑๒.๐๐ น.
ณ ห้องประชุม 1 ชั้น 2 สำนักงานทดสอบ จึงเรียนมาเพื่อโปรดเข้าร่วมประชุม"""


class AppointmentParseTests(SimpleTestCase):
    def test_invitation_letter(self):
        a = appointment.extract(INVITE, TODAY)
        self.assertEqual(a.subject, "ขอเชิญประชุมคณะทำงานตรวจสอบข้อเท็จจริง (ทดสอบ)")
        self.assertEqual(a.title, "ประชุมคณะทำงานตรวจสอบข้อเท็จจริง (ทดสอบ)")
        self.assertEqual(a.start_date, date(2026, 11, 26))  # ไม่ใช่วันที่หนังสือหรือลงวันที่ที่อ้างถึง
        self.assertEqual((a.start_time, a.end_time), (time(9, 30), time(12, 0)))
        self.assertEqual(a.location, "ห้องประชุม 1 ชั้น 2 สำนักงานทดสอบ")

    def test_memo_date_in_header_is_skipped_and_range_read(self):
        a = appointment.extract(
            "บันทึกข้อความ ส่วนราชการ กลุ่มงานทดสอบ ที่ ปช 0099/77 วันที่ 20 พฤศจิกายน 2569 เรื่อง ขออนุมัติเดินทางไปราชการ "
            "เรียน ผู้อำนวยการ ด้วยข้าพเจ้าจะเดินทางไปราชการ ระหว่างวันที่ 1 - 3 ธันวาคม 2569 ณ จังหวัดลำพูน เพื่อตรวจสอบ",
            TODAY,
        )
        self.assertEqual((a.start_date, a.end_date), (date(2026, 12, 1), date(2026, 12, 3)))
        self.assertIsNone(a.start_time)
        self.assertEqual(a.location, "จังหวัดลำพูน")

    def test_cross_month_range_and_abbreviated_month(self):
        a = appointment.extract("เรื่อง อบรม เรียน ทุกท่าน ระหว่างวันที่ 30 พฤศจิกายน - 2 ธันวาคม 2569 ณ โรงแรมทดสอบ", TODAY)
        self.assertEqual((a.start_date, a.end_date), (date(2026, 11, 30), date(2026, 12, 2)))
        b = appointment.extract("เรื่อง ประชุม เรียน ท่าน กำหนดประชุมวันที่ 5 ธ.ค. 69 เวลา 13:30 น. ณ ห้องประชุมใหญ่", TODAY)
        self.assertEqual((b.start_date, b.start_time), (date(2026, 12, 5), time(13, 30)))

    def test_ocr_spacing_and_missing_tone_marks(self):
        a = appointment.extract(
            "เรื่ อง ขอ เชิญ ประชุม เรียน ท่าน ใน วัน จันทร์ ที 7 ธัน วาคม 2569 เวลา 10.00 น. ณ ห้อง ประชุม 3 จึงเรียนมา",
            TODAY, ocr=True,
        )
        self.assertEqual((a.start_date, a.start_time), (date(2026, 12, 7), time(10, 0)))
        self.assertEqual(a.location, "ห้องประชุม 3")
        self.assertEqual(a.title, "ประชุม")

    def test_only_reference_date_means_no_appointment(self):
        a = appointment.extract("เรื่อง ขอข้อมูล เรียน ท่าน อ้างถึง หนังสือ ที่ ทส 1/2 ลงวันที่ 1 พฤศจิกายน 2569", TODAY)
        self.assertIsNone(a.start_date)
        self.assertTrue(a.notes)

    def test_google_url_and_ics(self):
        a = appointment.extract(INVITE, TODAY)
        url = appointment.google_url(a, "รายละเอียด")
        self.assertTrue(url.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE"))
        self.assertIn("dates=20261126T023000Z/20261126T050000Z", url)  # 09:30-12:00 เวลาไทย
        # ลิงก์ยาวเกินทำให้ Google ตอบ 400 จึงตัดรายละเอียดออกก่อน
        long_url = appointment.google_url(appointment.Appointment(title="ประชุม" * 40, start_date=date(2026, 12, 1),
                                                                   location="ห้อง" * 40), "รายละเอียด" * 60)
        self.assertLessEqual(len(long_url), appointment.GOOGLE_URL_MAX)
        self.assertIn("dates=20261201/20261202", long_url)
        ics = appointment.to_ics(a, uid="t@e", details="ก" * 80).decode("utf-8")
        self.assertIn("DTSTART:20261126T023000Z", ics)
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        whole_day = appointment.Appointment(title="x", start_date=date(2026, 12, 1), end_date=date(2026, 12, 3))
        self.assertIn("DTEND;VALUE=DATE:20261204", appointment.to_ics(whole_day, uid="u").decode())


def fake_text(text):
    return mock.patch.object(pdftext, "text_versions", return_value=[pdftext.TextResult(text, "pdfium")])


GARBLED = "เรื่ อง ขอเ ชญปรื่ะช$ม เรื่ยนั ท่าน ในัวนัพฤหสำบดที่ ๒๖ พฤศ จิกยนั ๒๕๖๙ เวล ๐๙. ๓๐ นั. " * 3


class ReadPipelineTests(SimpleTestCase):
    """เลือกผลจากตัวอ่านที่ได้ข้อความสะอาดที่สุด และใช้ OCR เมื่อชั้นข้อความไม่พอ"""

    def test_prefers_clean_reader_over_garbled(self):
        from .calendar_views import _read

        versions = [pdftext.TextResult(GARBLED, "text"), pdftext.TextResult(INVITE, "poppler")]
        with mock.patch.object(pdftext, "text_versions", return_value=versions), \
                mock.patch.object(pdftext, "ocr_version") as ocr:
            appt, notes = _read(b"%PDF")
        self.assertEqual(appt.start_date, date(2026, 11, 26))
        self.assertEqual(appt.location, "ห้องประชุม 1 ชั้น 2 สำนักงานทดสอบ")
        ocr.assert_not_called()  # ข้อมูลครบแล้วไม่ต้อง OCR

    def test_falls_back_to_ocr_and_merges(self):
        from .calendar_views import _read

        ocr_text = "เรื่อง ขอเชิญประชุม เรียน ท่าน ในวันจันทร์ที่ 7 ธันวาคม 2569 เวลา 10.00 น. ณ ห้องประชุม 3 จึงเรียนมา"
        with mock.patch.object(pdftext, "text_versions", return_value=[pdftext.TextResult(GARBLED, "text")]), \
                mock.patch.object(pdftext, "ocr_version", return_value=pdftext.TextResult(ocr_text, "ocr", pdftext.OCR_NOTE)):
            appt, notes = _read(b"%PDF")
        self.assertEqual((appt.start_date, appt.start_time), (date(2026, 12, 7), time(10, 0)))
        self.assertIn(pdftext.OCR_NOTE, notes)

    def test_scan_without_ocr_tells_user(self):
        from .calendar_views import _read

        with mock.patch.object(pdftext, "text_versions", return_value=[]), \
                mock.patch.object(pdftext, "ocr_version", return_value=None):
            appt, notes = _read(b"%PDF")
        self.assertIsNone(appt.start_date)
        self.assertIn(pdftext.NO_OCR_NOTE, notes)

    def test_ocr_digit_mixups_fixed_with_weekday(self):
        # OCR อ่าน ๖ เป็น ๒ และ ๙ เป็น ๕: "วันพุธที่ ๒๕ พฤศจิกายน ๒๕๒๕" ต้องได้ 25 พ.ย. 2569 ซึ่งเป็นวันพุธ
        scan = ("ที่ ทส 1/2 วันที่ 10 พฤศจิกายน 2569\nXyz ขอความร่วมมือตอบแบบสอบถาม (ทดสอบ) 7\nเรียน ผู้อำนวยการ\n"
                "โปรดส่งแบบสอบถาม ภายในวันพุธที่ ๒๕ พฤศจิกายน ๒๕๒๕ เพื่อประกอบการพิจารณา")
        a = appointment.extract(scan, date(2026, 11, 23), ocr=True)
        self.assertEqual(a.start_date, date(2026, 11, 25))
        self.assertEqual(a.start_date.weekday(), 2)
        # หาคำว่า "เรื่อง" ไม่เจอ ใช้บรรทัดก่อน "เรียน" และบอกว่าเป็นวันครบกำหนด
        self.assertEqual(a.title, "ครบกำหนด: ขอความร่วมมือตอบแบบสอบถาม (ทดสอบ)")
        self.assertTrue(any("อ่านไม่ชัด" in n for n in a.notes))

    def test_unfixable_year_is_left_blank(self):
        a = appointment.extract("เรื่อง ประชุม เรียน ท่าน ในวันที่ 15 พฤศจิกายน 2111 เวลา 09.30 น.", TODAY, ocr=True)
        self.assertIsNone(a.start_date)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class CalendarViewTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(code="C1", name_th="กลุ่มงานปฏิทิน")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK], clearance_level=SecrecyLevel.SECRET)
        self.doc = self.make_doc(SecrecyLevel.NORMAL)
        login_verified(self.client, self.clerk)

    def make_doc(self, secrecy):
        return register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": "ขอเชิญประชุม (ทดสอบ)", "source_doc_no": "x", "source_org": "y",
                  "owner_department": self.dept, "secrecy": secrecy},
            main_file=("เชิญประชุม.pdf", pdf_bytes(), 1), extra_files=[], user=self.clerk,
        )

    def url(self, doc=None):
        return reverse("documents:calendar", args=[(doc or self.doc).pk])

    def form_data(self, action):
        return {"title": "ประชุมคณะทำงาน", "start_date": "2026-11-26", "start_time": "09:30", "end_time": "12:00",
                "location": "ห้องประชุม 1", "subject": "ขอเชิญประชุม", "details": "", "action": action}

    def test_page_prefills_from_file(self):
        with fake_text(INVITE):
            page = self.client.get(self.url())
        self.assertContains(page, 'value="2026-11-26"')
        self.assertContains(page, 'value="09:30"')
        self.assertContains(page, "ห้องประชุม 1 ชั้น 2 สำนักงานทดสอบ")
        self.assertContains(page, "จาก y ที่ x")  # หน่วยงานและเลขที่หนังสือต้นทางเติมในรายละเอียด

    def test_google_export_is_logged(self):
        page = self.client.post(self.url(), self.form_data("google"))
        self.assertContains(page, "https://calendar.google.com/calendar/render?action=TEMPLATE")
        # คำอธิบายมีลิงก์กลับมาที่หนังสือ และมีปุ่มดาวน์โหลดไฟล์ไว้แนบที่ Google
        self.assertIn(reverse("documents:detail", args=[self.doc.pk]), page.context["google_url"])
        self.assertContains(page, f'{reverse("documents:file", args=[self.doc.main_attachment.pk])}?download=1')
        self.assertTrue(AuditEntry.objects.filter(action="CALENDAR_GOOGLE").exists())

    def test_ics_download(self):
        response = self.client.post(self.url(), self.form_data("ics"))
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        self.assertIn(b"BEGIN:VEVENT", b"".join(response.streaming_content))
        self.assertTrue(AuditEntry.objects.filter(action="CALENDAR_ICS").exists())

    def test_secret_document_cannot_go_to_google(self):
        secret = self.make_doc(SecrecyLevel.CONFIDENTIAL)
        page = self.client.post(self.url(secret), self.form_data("google"))
        self.assertNotContains(page, "calendar.google.com")
        self.assertFalse(AuditEntry.objects.filter(action="CALENDAR_GOOGLE").exists())

    def test_people_who_cannot_see_document_get_404(self):
        outsider = make_user("staff_x", roles=[(RoleCode.STAFF, Department.objects.create(code="C2", name_th="อื่น"))])
        login_verified(self.client, outsider)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_upload_page_requires_confirmation_before_google(self):
        with fake_text(INVITE):
            review = self.client.post(reverse("documents:calendar_upload"), {"file": pdf_upload()})
        self.assertContains(review, 'value="2026-11-26"')
        data = self.form_data("google")
        page = self.client.post(reverse("documents:calendar_upload"), data)
        self.assertNotContains(page, "calendar.google.com")
        page = self.client.post(reverse("documents:calendar_upload"), {**data, "not_secret": "on"})
        self.assertContains(page, "calendar.google.com")

    def test_upload_rejects_non_pdf(self):
        page = self.client.post(reverse("documents:calendar_upload"), {"file": pdf_upload(content=b"not a pdf")})
        self.assertContains(page, "ไม่ใช่ไฟล์ PDF จริง")

    def test_admin_does_not_get_calendar(self):
        login_verified(self.client, make_admin())
        self.assertEqual(self.client.get(reverse("documents:calendar_upload")).status_code, 403)
