"""
วางภาพลายมือชื่อลงบน PDF (ไม่ import Django จึงทดสอบแยกได้)

สิ่งที่ได้คือ "ภาพลายมือชื่อบนเอกสาร" เท่านั้น ไม่ใช่ลายมือชื่ออิเล็กทรอนิกส์ที่ตรวจสอบได้ด้วยใบรับรอง
ความน่าเชื่อถือมาจากบันทึกในระบบ (ใครลงนาม เมื่อไหร่ ยืนยันตัวตนด้วย MFA และ hash ของไฟล์) ไม่ใช่จากตัวไฟล์
"""
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

MAX_SIGNATURE_BYTES = 2 * 1024 * 1024
MAX_SIDE_PX = 3000
WHITE_THRESHOLD = 235  # พิกเซลที่สว่างกว่านี้ถือเป็นพื้นกระดาษ ทำให้โปร่งใส

MIN_WIDTH_RATIO = 0.05  # ความกว้างภาพเทียบความกว้างหน้า
MAX_WIDTH_RATIO = 0.6


class StampError(ValueError):
    pass


def clean_signature_image(data):
    """ตรวจและแปลงภาพลายเซ็นเป็น PNG พื้นโปร่งใส ตัด metadata ทั้งหมด คืนค่า (png_bytes, width, height)"""
    if not data:
        raise StampError("ไม่พบไฟล์ภาพ")
    if len(data) > MAX_SIGNATURE_BYTES:
        raise StampError("ไฟล์ภาพใหญ่เกิน 2 MB")
    try:
        probe = Image.open(BytesIO(data))
        fmt = probe.format
        probe.verify()
        image = Image.open(BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise StampError("ไม่ใช่ไฟล์ภาพที่ถูกต้อง") from exc
    if fmt not in ("PNG", "JPEG"):
        raise StampError("รับเฉพาะไฟล์ PNG หรือ JPG")
    if max(image.size) > MAX_SIDE_PX or min(image.size) < 20:
        raise StampError(f"ขนาดภาพต้องอยู่ระหว่าง 20 ถึง {MAX_SIDE_PX} พิกเซล")

    image = image.convert("RGBA")
    pixels = [
        (r, g, b, 0) if r > WHITE_THRESHOLD and g > WHITE_THRESHOLD and b > WHITE_THRESHOLD else (r, g, b, a)
        for (r, g, b, a) in image.getdata()
    ]
    image.putdata(pixels)
    bbox = image.getbbox()
    if bbox is None:
        raise StampError("ภาพว่างเปล่า ไม่พบลายเส้นลายเซ็น")
    image = image.crop(bbox)
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), image.width, image.height


def page_count(pdf_bytes):
    try:
        return len(PdfReader(BytesIO(pdf_bytes)).pages)
    except Exception as exc:  # noqa: BLE001 ไฟล์จากภายนอกอาจทำให้ไลบรารี error ได้หลายแบบ
        raise StampError("อ่านไฟล์ PDF ไม่ได้") from exc


def _open_writer(pdf_bytes):
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        if reader.is_encrypted:
            raise StampError("ไฟล์ PDF ติดรหัสผ่าน")
        return PdfWriter(clone_from=reader)
    except StampError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise StampError("อ่านไฟล์ PDF ไม่ได้") from exc


def page_size(pdf_bytes, page_number):
    """ขนาดหน้าตามที่เห็นบนจอ (หลังหมุนแล้ว) เป็น point คืนค่า (กว้าง, สูง)"""
    writer = _open_writer(pdf_bytes)
    if not 1 <= page_number <= len(writer.pages):
        raise StampError(f"เลขหน้าต้องอยู่ระหว่าง 1 ถึง {len(writer.pages)}")
    page = writer.pages[page_number - 1]
    page.transfer_rotation_to_content()
    return float(page.cropbox.width), float(page.cropbox.height)


def stamp_images(pdf_bytes, stamps):
    """
    วางภาพหลายภาพลงบน PDF ในครั้งเดียว
    stamps: รายการ dict {page, x, y, png, width_ratio}
      x, y = มุมซ้ายบนของภาพเป็นสัดส่วนของหน้าตามที่เห็นบนจอ (0–1)
      width_ratio = ความกว้างภาพเทียบความกว้างหน้า (0–1)
    คืนค่า bytes ของ PDF ใหม่ ไฟล์ต้นฉบับไม่ถูกแก้ไข
    """
    writer = _open_writer(pdf_bytes)
    by_page = {}
    for stamp in stamps:
        if not (0 <= stamp["x"] <= 1 and 0 <= stamp["y"] <= 1):
            raise StampError("ตำแหน่งไม่ถูกต้อง")
        if not 0 < stamp["width_ratio"] <= 1:
            raise StampError("ขนาดไม่ถูกต้อง")
        if not 1 <= stamp["page"] <= len(writer.pages):
            raise StampError(f"เลขหน้าต้องอยู่ระหว่าง 1 ถึง {len(writer.pages)}")
        by_page.setdefault(stamp["page"], []).append(stamp)

    for page_number, items in by_page.items():
        page = writer.pages[page_number - 1]
        page.transfer_rotation_to_content()  # ให้พิกัดตรงกับหน้าตามที่เห็นบนจอ (หน้าที่หมุนไว้)
        box = page.cropbox  # พื้นที่ที่แสดงจริง (ตัวดู PDF ใช้กรอบเดียวกัน)
        left, bottom = float(box.left), float(box.bottom)
        width, height = float(box.width), float(box.height)
        overlay = BytesIO()
        c = canvas.Canvas(overlay, pagesize=(left + width, bottom + height))
        for item in items:
            image = Image.open(BytesIO(item["png"]))
            draw_w = min(width * item["width_ratio"], width)
            draw_h = draw_w * image.height / image.width
            px = left + width * item["x"]
            py = bottom + height * (1 - item["y"]) - draw_h  # PDF นับแกน y จากล่างขึ้นบน
            px = min(max(px, left), left + width - draw_w)
            py = min(max(py, bottom), bottom + max(height - draw_h, 0))
            c.drawImage(ImageReader(image), px, py, width=draw_w, height=draw_h, mask="auto")
        c.save()
        page.merge_page(PdfReader(BytesIO(overlay.getvalue())).pages[0])

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def stamp_signature(pdf_bytes, png_bytes, *, page_number, x, y, width_ratio):
    """วางภาพลายมือชื่อ 1 ภาพ (ตรวจขนาดตามข้อกำหนดของลายเซ็น)"""
    if not MIN_WIDTH_RATIO <= width_ratio <= MAX_WIDTH_RATIO:
        raise StampError("ขนาดลายเซ็นไม่ถูกต้อง")
    return stamp_images(pdf_bytes, [{"page": page_number, "x": x, "y": y, "png": png_bytes, "width_ratio": width_ratio}])
