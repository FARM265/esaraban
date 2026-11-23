"""
ตรวจไฟล์ PDF ที่อัปโหลด (ไม่ import Django จึงทดสอบแยกได้)

ตรวจจากเนื้อไฟล์จริง ไม่เชื่อนามสกุลหรือ content-type ที่เบราว์เซอร์ส่งมา
ข้อจำกัด: ถ้า JavaScript ถูกซ่อนใน object stream ที่บีบอัด การค้นหาข้อความจะไม่พบ
ระบบจึงแสดงไฟล์ผ่าน PDF.js (ขั้นตอนที่ 7) ซึ่งไม่รันสคริปต์ใน PDF อีกชั้นหนึ่ง
"""
import re

PDF_MAGIC = b"%PDF-"

# คำสั่งใน PDF ที่สั่งรันสคริปต์หรือเปิดโปรแกรมภายนอก
_DANGEROUS = [
    (re.compile(rb"/JavaScript\b"), "มี JavaScript ฝังอยู่"),
    (re.compile(rb"/JS[\s(<\[/]"), "มี JavaScript ฝังอยู่"),
    (re.compile(rb"/Launch\b"), "มีคำสั่งเปิดโปรแกรมภายนอก (/Launch)"),
    (re.compile(rb"/EmbeddedFile\b"), "มีไฟล์อื่นฝังอยู่ใน PDF"),
    (re.compile(rb"/XFA\b"), "เป็นฟอร์ม XFA ซึ่งรองรับสคริปต์"),
]
_PAGE_RE = re.compile(rb"/Type\s*/Page[^s]")


class PDFRejected(ValueError):
    pass


def check_pdf(data, max_bytes):
    """คืนค่าจำนวนหน้าโดยประมาณ (หรือ None) ถ้าไฟล์ไม่ผ่านจะ raise PDFRejected พร้อมเหตุผลภาษาไทย"""
    if not data:
        raise PDFRejected("ไฟล์ว่างเปล่า")
    if len(data) > max_bytes:
        raise PDFRejected(f"ไฟล์ใหญ่เกิน {max_bytes // (1024 * 1024)} MB")
    # บังคับให้ไฟล์ขึ้นต้นด้วย %PDF- เลย (เข้มกว่ามาตรฐาน) เพื่อกันไฟล์ที่ซ่อนโปรแกรมไว้ข้างหน้า
    if not data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(PDF_MAGIC):
        raise PDFRejected("ไม่ใช่ไฟล์ PDF จริง (เนื้อไฟล์ไม่ตรงกับรูปแบบ PDF)")
    if b"%%EOF" not in data[-2048:]:
        raise PDFRejected("ไฟล์ PDF ไม่สมบูรณ์ อาจอัปโหลดไม่ครบ")
    if b"/Encrypt" in data:
        # รวมถึง PDF ที่ล็อกสิทธิ์พิมพ์/คัดลอก ซึ่งระบบตรวจเนื้อในไม่ได้ทั้งหมด
        raise PDFRejected(
            "ไฟล์ PDF ติดรหัสผ่านหรือล็อกสิทธิ์ไว้ ให้เปิดไฟล์แล้วสั่งพิมพ์เป็น PDF ใหม่ (Microsoft Print to PDF) ก่อนอัปโหลด"
        )
    for pattern, reason in _DANGEROUS:
        if pattern.search(data):
            raise PDFRejected(f"ไม่อนุญาตไฟล์นี้: {reason}")
    pages = len(_PAGE_RE.findall(data))
    return pages or None
