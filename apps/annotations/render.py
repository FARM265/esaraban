"""
แปลงข้อความสั่งการ/เกษียนเป็นภาพ PNG พื้นโปร่งใส เพื่อฝังลงใน PDF (ไม่ import Django จึงทดสอบแยกได้)

ภาษาไทยต้องจัดตำแหน่งสระและวรรณยุกต์ (text shaping) จึงใช้ Pillow + libraqm
ถ้าเครื่องไม่มี raqm ระบบยังทำงานได้ แต่วรรณยุกต์บางตัวอาจซ้อนกับสระบน
ระยะบรรทัดตั้งให้ตรงกับ CSS ของตัวดู PDF (line-height 1.4) เพื่อให้ไฟล์ตรงกับที่เห็นบนจอ
"""
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, features

LINE_HEIGHT = 1.4
SCALE = 4  # พิกเซลต่อ 1 point (ประมาณ 288 dpi) ให้ตัวอักษรคมชัดเมื่อพิมพ์
MAX_LINES = 30


def has_complex_shaping():
    return features.check("raqm")


def render_text(text, *, color_hex, font_pt, font_path):
    """คืนค่า (png_bytes, width_pt) ภาพมีความกว้างพอดีข้อความ"""
    lines = text.splitlines() or [""]
    if len(lines) > MAX_LINES:
        raise ValueError(f"ข้อความยาวเกิน {MAX_LINES} บรรทัด")
    layout = ImageFont.Layout.RAQM if has_complex_shaping() else ImageFont.Layout.BASIC
    font_px = max(4, round(font_pt * SCALE))
    font = ImageFont.truetype(str(font_path), size=font_px, layout_engine=layout, encoding="unic")
    ascent, descent = font.getmetrics()
    line_px = font_px * LINE_HEIGHT
    half_leading = (line_px - (ascent + descent)) / 2

    width = max(1, round(max(font.getlength(line) for line in lines))) + font_px // 4
    height = max(1, round(line_px * len(lines)))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    rgb = tuple(int(color_hex[i:i + 2], 16) for i in (1, 3, 5))
    for index, line in enumerate(lines):
        top = index * line_px + half_leading
        draw.text((0, top), line, font=font, fill=(*rgb, 255), anchor="la")

    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), width / SCALE
