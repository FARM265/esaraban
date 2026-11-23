"""
ดึงข้อความจาก PDF สำหรับอ่านวันนัดหมาย

1) อ่านชั้นข้อความใน PDF ก่อน (หนังสือที่สร้างจากระบบหรือพิมพ์จาก Word)
2) ถ้าแทบไม่มีข้อความ (ภาพสแกน) และเครื่องมี tesseract พร้อมภาษาไทย จะ OCR เฉพาะหน้าแรก ๆ
ทำงานในหน่วยความจำทั้งหมด ไม่เขียนไฟล์เอกสารลงดิสก์
"""
import io
import logging
import re
import shutil
import subprocess

from django.conf import settings
from pypdf import PdfReader

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 40  # ตัวอักษรไทย/ตัวเลขขั้นต่ำที่ถือว่า PDF มีชั้นข้อความจริง


class TextResult:
    def __init__(self, text="", method="", note=""):
        self.text, self.method, self.note = text, method, note

    @property
    def ocr(self):
        return self.method == "ocr"


def _meaningful(text):
    return len(re.findall(r"[฀-๿0-9]", text or ""))


def text_layer(data, max_pages):
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:max_pages]:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception:  # noqa: BLE001  ไฟล์เสียหรืออ่านไม่ได้ ให้ลอง OCR ต่อ
        log.warning("อ่านชั้นข้อความ PDF ไม่ได้", exc_info=True)
        return ""


def ocr_available():
    return bool(getattr(settings, "ESARABAN_OCR_ENABLED", True) and shutil.which("tesseract"))


def ocr(data, max_pages):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        texts = []
        for index in range(min(len(pdf), max_pages)):
            page = pdf[index]
            image = page.render(scale=250 / 72, grayscale=True).to_pil()  # ประมาณ 250 dpi
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            proc = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", "tha+eng", "--psm", "6"],
                input=buf.getvalue(), capture_output=True, timeout=40, check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:200])
            texts.append(proc.stdout.decode("utf-8", "replace"))
        return "\n".join(texts)
    finally:
        pdf.close()


def pdfium_text(data, max_pages):
    """ตัวอ่านของ pdfium อ่าน PDF ภาษาไทยที่สร้างจาก Word ได้ถูกต้องกว่า pypdf มาก (pypdf มักได้สระวรรณยุกต์เพี้ยน)"""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception:  # noqa: BLE001
        log.warning("pdfium อ่านไฟล์ไม่ได้", exc_info=True)
        return ""
    try:
        parts = []
        for index in range(min(len(pdf), max_pages)):
            textpage = pdf[index].get_textpage()
            parts.append(textpage.get_text_range())
            textpage.close()
        return "\n".join(parts)
    finally:
        pdf.close()


def poppler_text(data, max_pages):
    """pdftotext (poppler) อ่าน PDF จาก Word บางฟอนต์ได้ดีกว่า pdfium ใช้เมื่อเครื่องมีโปรแกรมนี้"""
    if not shutil.which("pdftotext"):
        return ""
    try:
        proc = subprocess.run(
            ["pdftotext", "-q", "-l", str(max_pages), "-enc", "UTF-8", "-", "-"],
            input=data, capture_output=True, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        log.warning("pdftotext ไม่สำเร็จ", exc_info=True)
        return ""
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else ""


# คำที่พบบ่อยในหนังสือราชการ ใช้วัดว่าข้อความที่อ่านได้ "สะอาด" แค่ไหน
# (ตัวอ่านบางตัวได้สระวรรณยุกต์เพี้ยนหรือซ้ำ ทำให้หาคำเหล่านี้ไม่เจอ)
_VOCAB = (
    "เรื่อง เรียน ขอเชิญ ประชุม สำนักงาน หน่วยงาน ห้องประชุม ชั้น เวลา วันที่ ในวัน จึงเรียนมา เพื่อโปรด พิจารณา "
    "ดำเนินการ ข้อมูล ผู้อำนวยการ จังหวัด อำเภอ ตำบล มกราคม กุมภาพันธ์ มีนาคม เมษายน พฤษภาคม มิถุนายน กรกฎาคม "
    "สิงหาคม กันยายน ตุลาคม พฤศจิกายน ธันวาคม จันทร์ อังคาร พุธ พฤหัสบดี ศุกร์ เสาร์ อาทิตย์ เข้าร่วม ทั้งนี้ "
    "ดังกล่าว อนุเคราะห์ ราชการ"
).split()


def quality(text):
    flat = re.sub(r"\s+", " ", text or "").replace("\u0e4d\u0e32", "\u0e33")
    return sum(flat.count(word) for word in _VOCAB)


OCR_NOTE = "อ่านจากภาพ (OCR) อาจมีตัวอักษรผิด กรุณาตรวจทุกช่อง"


def text_versions(data):
    """ข้อความจากชั้นข้อความของ PDF ด้วยตัวอ่านหลายตัว (เร็ว) เฉพาะที่มีข้อความจริง"""
    max_pages = getattr(settings, "ESARABAN_OCR_MAX_PAGES", 2)
    out = []
    for method, reader in (("pdfium", pdfium_text), ("poppler", poppler_text), ("text", text_layer)):
        text = reader(data, max_pages)
        if _meaningful(text) >= MIN_TEXT_CHARS:
            out.append(TextResult(text, method))
    return out


def ocr_version(data):
    """อ่านจากภาพ (ช้ากว่า) คืน TextResult หรือ None ถ้าเครื่องไม่มี OCR"""
    if not ocr_available():
        return None
    try:
        return TextResult(ocr(data, getattr(settings, "ESARABAN_OCR_MAX_PAGES", 2)), "ocr", OCR_NOTE)
    except Exception:  # noqa: BLE001
        log.warning("OCR ไม่สำเร็จ", exc_info=True)
        return TextResult("", "none", "อ่านข้อความจากภาพไม่สำเร็จ กรุณากรอกข้อมูลเอง")


NO_OCR_NOTE = "ไฟล์นี้เป็นภาพสแกน และเครื่องนี้ยังไม่ได้ติดตั้งโปรแกรมอ่านภาพ (OCR) กรุณากรอกข้อมูลเอง"
