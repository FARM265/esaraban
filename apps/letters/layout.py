"""
สร้างไฟล์ PDF หนังสือราชการจากแม่แบบ 4 แบบ ตามรูปแบบในระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ
(หนังสือภายนอก บันทึกข้อความ คำสั่ง ประกาศ)

ข้อความไทยต้องจัดตำแหน่งสระและวรรณยุกต์ (shaping) ซึ่ง reportlab ทำไม่ได้ จึงวาดข้อความแต่ละบรรทัด
ด้วย Pillow + libraqm เป็นภาพความละเอียดสูง แล้ววางลงใน PDF พร้อมชั้นข้อความที่มองไม่เห็นทับไว้
ผู้ใช้จึงค้นหาและคัดลอกข้อความจากไฟล์ได้ ตัดคำขึ้นบรรทัดใหม่ด้วย libthai (thaibreak)

ไม่ import Django จึงทดสอบแยกได้ ผลลัพธ์คือ bytes ของ PDF และตำแหน่งสำหรับประทับเลขที่/วันที่/ลายเซ็นภายหลัง
"""
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, features
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from . import thaibreak

PAGE_W, PAGE_H = A4
MM = 72 / 25.4
SCALE = 4  # พิกเซลต่อ point (ประมาณ 288 dpi)

LEFT = 30 * MM
RIGHT = PAGE_W - 20 * MM
TOP = 25 * MM
BOTTOM = 20 * MM
BODY = 14            # ขนาดตัวอักษรเนื้อหา (Sarabun 14 ใกล้เคียง TH Sarabun New 16)
LH = 20              # ระยะบรรทัด
PARA_INDENT = 25 * MM
CENTER = PAGE_W / 2
RED = "#C00000"

KINDS = ("OUTGOING", "INTERNAL", "ORDER", "ANNOUNCE")


@dataclass
class LetterSpec:
    kind: str
    org_name: str
    subject: str
    body: list = field(default_factory=list)            # ย่อหน้า
    recipient: str = ""
    reference: str = ""
    enclosures: list = field(default_factory=list)
    closing: str = ""
    signer_name: str = ""
    signer_position: list = field(default_factory=list)
    org_address: list = field(default_factory=list)
    department_line: str = ""                           # ส่วนราชการ (บันทึกข้อความ)
    contact: list = field(default_factory=list)         # ส่วนราชการเจ้าของเรื่อง โทร (หนังสือภายนอก)
    urgency: str = ""
    secrecy: str = ""
    emblem_png: bytes = None


@dataclass
class Result:
    pdf: bytes
    pages: int
    number_anchor: dict = None   # {"page", "x", "baseline"} หน่วย point วัดจากมุมซ้ายบน
    date_anchor: dict = None
    sign_anchor: dict = None     # {"page", "x", "y", "w"} สัดส่วนของหน้า สำหรับวางลายเซ็นเริ่มต้น


class Typesetter:
    """วัด ตัดบรรทัด และวาดข้อความไทยลงบน canvas ของ reportlab"""

    def __init__(self, regular_path, bold_path=None):
        self.paths = {False: str(regular_path), True: str(bold_path or regular_path)}
        self.layout = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
        self.pdf_font = {}
        for bold, path in self.paths.items():
            name = f"ES-{abs(hash(path)) % 10**8}"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))
            self.pdf_font[bold] = name

    @lru_cache(maxsize=32)
    def font(self, size, bold=False):
        return ImageFont.truetype(self.paths[bold], size=round(size * SCALE), layout_engine=self.layout)

    def width(self, text, size, bold=False):
        return self.font(size, bold).getlength(text) / SCALE if text else 0

    def wrap(self, text, size, width, bold=False, first_width=None):
        """ตัดข้อความเป็นบรรทัด บรรทัดแรกกว้าง first_width (ใช้กับย่อหน้าที่ย่อหน้าแรก)"""
        lines, current = [], ""
        limit = first_width if first_width is not None else width
        pieces = list(thaibreak.atoms(text.strip()))
        while pieces:
            piece = pieces.pop(0)
            candidate = current + piece
            if self.width(candidate.rstrip(), size, bold) <= limit or not current.strip():
                if self.width(candidate.rstrip(), size, bold) > limit:
                    # คำเดียวยาวเกินบรรทัด: ตัดกลางคำตามกลุ่มอักษร
                    head, rest = "", thaibreak.clusters(piece)
                    while rest and self.width(current + head + rest[0], size, bold) <= limit:
                        head += rest.pop(0)
                    if not head and not current:
                        head = rest.pop(0)
                    lines.append((current + head).rstrip())
                    current = ""
                    limit = width
                    if rest:
                        pieces.insert(0, "".join(rest))
                    continue
                current = candidate
            else:
                lines.append(current.rstrip())
                current = ""
                limit = width
                pieces.insert(0, piece)
        if current.strip() or not lines:
            lines.append(current.rstrip())
        return lines

    def render(self, text, size, bold=False, color="#000000"):
        """ภาพ PNG ของข้อความ 1 บรรทัด คืนค่า (png, dx, dy_top, w, h) หน่วย point เทียบกับจุดเริ่มบน baseline"""
        image, dx, dy, w, h = self.render_image(text, size, bold, color)
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue(), dx, dy, w, h

    def render_image(self, text, size, bold=False, color="#000000"):
        """เหมือน render แต่คืนภาพ Pillow (ส่งให้ reportlab ได้ตรง ไม่ต้องเข้ารหัส PNG ซ้ำ ซึ่งช้า)"""
        font = self.font(size, bold)
        left, top, right, bottom = font.getbbox(text, anchor="ls")
        pad = 2
        w, h = right - left + 2 * pad, bottom - top + 2 * pad
        image = Image.new("RGBA", (max(w, 1), max(h, 1)), (0, 0, 0, 0))
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        ImageDraw.Draw(image).text((pad - left, pad - top), text, font=font, fill=(*rgb, 255), anchor="ls")
        return image, (left - pad) / SCALE, (top - pad) / SCALE, w / SCALE, h / SCALE

    def draw(self, c, x, baseline, text, size, bold=False, color="#000000"):
        """วาดข้อความที่ (x, baseline) หน่วย point วัดจากมุมซ้ายบนของหน้า"""
        if not text.strip():
            return
        image, dx, dy, w, h = self.render_image(text, size, bold, color)
        y_pdf = PAGE_H - baseline
        c.drawImage(ImageReader(image), x + dx, y_pdf - (dy + h), width=w, height=h, mask="auto")
        # ชั้นข้อความที่มองไม่เห็น เพื่อค้นหาและคัดลอกข้อความได้
        name = self.pdf_font[bold]
        natural = pdfmetrics.stringWidth(text, name, size)
        target = self.width(text, size, bold)
        t = c.beginText(x, y_pdf)
        t.setTextRenderMode(3)
        t.setFont(name, size)
        if natural > 0:
            t.setHorizScale(max(10, min(400, target / natural * 100)))
        t.textOut(text)
        c.drawText(t)


class _Writer:
    """จัดหน้าแบบไหลต่อเนื่อง ขึ้นหน้าใหม่อัตโนมัติ"""

    def __init__(self, spec, ts):
        self.spec, self.ts = spec, ts
        self.buf = BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4, pageCompression=1)
        self.c.setTitle(spec.subject[:200])
        self.c.setCreator("E-Saraban")
        self.page = 1
        self.y = TOP
        self._decorate()

    # ----- ส่วนประกอบประจำหน้า
    def _decorate(self):
        if self.spec.secrecy:
            for baseline in (12 * MM + 8, PAGE_H - 10 * MM):
                w = self.ts.width(self.spec.secrecy, 20, True)
                self.ts.draw(self.c, CENTER - w / 2, baseline, self.spec.secrecy, 20, True, RED)
        if self.page > 1:
            label = f"- {self.page} -"
            self.ts.draw(self.c, CENTER - self.ts.width(label, BODY) / 2, 15 * MM, label, BODY)

    def new_page(self):
        self.c.showPage()
        self.page += 1
        self.y = TOP + LH
        self._decorate()

    def ensure(self, height):
        if self.y + height > PAGE_H - BOTTOM:
            self.new_page()

    # ----- ข้อความ
    def line(self, x, text, size=BODY, bold=False, color="#000000"):
        self.ensure(LH)
        self.ts.draw(self.c, x, self.y, text, size, bold, color)
        self.y += LH

    def centered(self, text, size=BODY, bold=False, width=None):
        width = width or (RIGHT - LEFT)
        for part in self.ts.wrap(text, size, width, bold):
            self.ensure(LH)
            self.ts.draw(self.c, CENTER - self.ts.width(part, size, bold) / 2, self.y, part, size, bold)
            self.y += LH * size / BODY

    def labelled(self, label, value, bold_label=False, gap=8):
        """ป้ายกำกับ เช่น "เรื่อง" ตามด้วยข้อความที่ตัดบรรทัดแบบแขวน"""
        x_value = LEFT + self.ts.width(label, BODY, bold_label) + gap
        lines = self.ts.wrap(value, BODY, RIGHT - x_value)
        self.ensure(LH)
        self.ts.draw(self.c, LEFT, self.y, label, BODY, bold_label)
        for text in lines:
            self.ensure(LH)
            self.ts.draw(self.c, x_value, self.y, text, BODY)
            self.y += LH

    def paragraph(self, text, indent=PARA_INDENT):
        lines = self.ts.wrap(text, BODY, RIGHT - LEFT, first_width=RIGHT - LEFT - indent)
        for index, part in enumerate(lines):
            self.ensure(LH)
            self.ts.draw(self.c, LEFT + (indent if index == 0 else 0), self.y, part, BODY)
            self.y += LH

    def emblem(self, height_mm, x=None, top_mm=15):
        h = height_mm * MM
        if self.spec.emblem_png:
            image = Image.open(BytesIO(self.spec.emblem_png))
            w = h * image.width / image.height
            left = CENTER - w / 2 if x is None else x
            self.c.drawImage(ImageReader(image), left, PAGE_H - top_mm * MM - h, width=w, height=h, mask="auto")
        return top_mm * MM + h

    def signature_block(self, axis, closing=""):
        """คำลงท้าย (ถ้ามี) ที่ว่างสำหรับลงนาม ชื่อในวงเล็บ และตำแหน่ง จัดกึ่งกลางที่แกน axis"""
        names = [f"({self.spec.signer_name})"] if self.spec.signer_name else []
        block = (1 if closing else 0) + 3 + len(names) + len(self.spec.signer_position)
        self.ensure(block * LH)
        if closing:
            self.ts.draw(self.c, axis - self.ts.width(closing, BODY) / 2, self.y, closing, BODY)
            self.y += LH
        sig_w = 0.25 * PAGE_W
        anchor = {
            "page": self.page,
            "x": round((axis - sig_w / 2) / PAGE_W, 4),
            "y": round((self.y - LH * 0.6) / PAGE_H, 4),
            "w": 0.25,
        }
        self.y += 2.4 * LH
        for text in names + list(self.spec.signer_position):
            self.ensure(LH)
            self.ts.draw(self.c, axis - self.ts.width(text, BODY) / 2, self.y, text, BODY)
            self.y += LH
        return anchor

    def finish(self):
        self.c.save()
        return self.buf.getvalue()


def _anchor(writer, x):
    return {"page": writer.page, "x": round(x, 2), "baseline": round(writer.y, 2), "size": BODY}


def _urgency(w):
    if w.spec.urgency:
        w.ts.draw(w.c, LEFT, 22 * MM, w.spec.urgency, 20, True, RED)


def build(spec, regular_font, bold_font=None):
    if spec.kind not in KINDS:
        raise ValueError("ไม่รู้จักแม่แบบนี้")
    ts = Typesetter(regular_font, bold_font)
    w = _Writer(spec, ts)
    builders = {"OUTGOING": _outgoing, "INTERNAL": _internal, "ORDER": _order, "ANNOUNCE": _announce}
    number, date, sign = builders[spec.kind](w)
    return Result(pdf=w.finish(), pages=w.page, number_anchor=number, date_anchor=date, sign_anchor=sign)


# ---------------------------------------------------------------- แม่แบบ
def _outgoing(w):
    s, ts = w.spec, w.ts
    _urgency(w)
    w.y = w.emblem(30) + 9 * MM
    top = w.y
    number = _anchor(w, LEFT + ts.width("ที่ ", BODY))
    w.line(LEFT, "ที่")
    # ส่วนราชการเจ้าของหนังสือและที่ตั้ง ชิดขวา
    w.y = top
    org_x = 118 * MM
    for text in [s.org_name, *s.org_address]:
        for part in ts.wrap(text, BODY, RIGHT - org_x):
            w.line(org_x, part)
    w.y = max(w.y, top + LH) + LH * 0.5
    date = _anchor(w, CENTER)
    w.y += LH * 1.5
    w.labelled("เรื่อง", s.subject)
    w.y += 4
    w.labelled("เรียน", s.recipient)
    if s.reference:
        w.y += 4
        w.labelled("อ้างถึง", s.reference)
    if s.enclosures:
        w.y += 4
        label = "สิ่งที่ส่งมาด้วย"
        items = s.enclosures if len(s.enclosures) == 1 else [f"{i}. {t}" for i, t in enumerate(s.enclosures, 1)]
        w.labelled(label, items[0])
        for item in items[1:]:
            _hanging(w, label, item)
    w.y += 8
    for text in s.body:
        w.paragraph(text)
        w.y += 4
    w.y += LH * 0.5
    sign = w.signature_block(axis=CENTER + 20 * MM, closing=s.closing or "ขอแสดงความนับถือ")
    if s.contact:
        need = LH * (len(s.contact) + 1)
        bottom_start = PAGE_H - BOTTOM - LH * len(s.contact)
        if w.y + need <= bottom_start:
            w.y = bottom_start
        else:
            w.y += LH
        for text in s.contact:
            w.line(LEFT, text)
    return number, date, sign


def _hanging(w, label, item):
    x_value = LEFT + w.ts.width(label, BODY) + 8
    for text in w.ts.wrap(item, BODY, RIGHT - x_value):
        w.line(x_value, text)


def _internal(w):
    s, ts = w.spec, w.ts
    _urgency(w)
    emblem_bottom = w.emblem(15, x=LEFT, top_mm=15)
    title = "บันทึกข้อความ"
    ts.draw(w.c, CENTER - ts.width(title, 24, True) / 2, emblem_bottom - 3, title, 24, True)
    w.y = emblem_bottom + LH
    w.labelled("ส่วนราชการ", s.department_line or s.org_name, bold_label=True)
    number = _anchor(w, LEFT + ts.width("ที่", BODY, True) + 8)
    date_x = CENTER - 10 * MM
    date = {**_anchor(w, date_x + ts.width("วันที่", BODY, True) + 8)}
    w.ts.draw(w.c, LEFT, w.y, "ที่", BODY, True)
    w.ts.draw(w.c, date_x, w.y, "วันที่", BODY, True)
    w.y += LH
    w.labelled("เรื่อง", s.subject, bold_label=True)
    w.c.setLineWidth(0.5)
    w.c.line(LEFT, PAGE_H - (w.y - LH * 0.55), RIGHT, PAGE_H - (w.y - LH * 0.55))
    w.y += LH * 0.5
    w.labelled("เรียน", s.recipient)
    w.y += 6
    for text in s.body:
        w.paragraph(text)
        w.y += 4
    w.y += LH * 0.5
    sign = w.signature_block(axis=CENTER + 20 * MM)
    return number, date, sign


def _order_like(w, title, date_label, numbered):
    s, ts = w.spec, w.ts
    _urgency(w)
    w.y = w.emblem(30) + 9 * MM
    w.centered(f"{title}{s.org_name}", BODY + 2, True)
    number = None
    if numbered:
        prefix = "ที่ "
        reserve = 70  # ที่ว่างสำหรับเลขที่ (ประทับเมื่อออกเลข)
        x = CENTER - (ts.width(prefix, BODY + 2, True) + reserve) / 2
        ts.draw(w.c, x, w.y, prefix, BODY + 2, True)
        number = {**_anchor(w, x + ts.width(prefix, BODY + 2, True)), "size": BODY + 2}
        w.y += LH
    w.centered(f"เรื่อง  {s.subject}", BODY + 2, True)
    w.c.setLineWidth(0.6)
    rule_y = PAGE_H - (w.y - LH * 0.35)
    w.c.line(CENTER - 25 * MM, rule_y, CENTER + 25 * MM, rule_y)
    w.y += LH * 0.8
    for text in s.body:
        w.paragraph(text)
        w.y += 4
    w.y += LH * 0.5
    w.ensure(LH * 7)
    x = CENTER - 5 * MM
    date = _anchor(w, x + ts.width(date_label + " ", BODY))
    w.line(x, date_label)
    w.y += LH * 0.5
    sign = w.signature_block(axis=CENTER + 20 * MM)
    return number, date, sign


def _order(w):
    return _order_like(w, "คำสั่ง", "สั่ง ณ วันที่", numbered=True)


def _announce(w):
    return _order_like(w, "ประกาศ", "ประกาศ ณ วันที่", numbered=False)


# ---------------------------------------------------------------- ประทับเลขที่และวันที่ภายหลัง
def anchor_stamp(ts, anchor, text, page_w=PAGE_W, page_h=PAGE_H):
    """แปลงข้อความ + ตำแหน่ง baseline เป็นรายการสำหรับ stamping.stamp_images"""
    size = anchor.get("size", BODY)
    png, dx, dy, w, h = ts.render(text, size)
    return {
        "page": anchor["page"],
        "x": (anchor["x"] + dx) / page_w,
        "y": (anchor["baseline"] + dy) / page_h,
        "png": png,
        "width_ratio": w / page_w,
    }
