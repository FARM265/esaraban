"""
ส่งออกหนังสือจากแม่แบบเป็นไฟล์ Word (.docx) เพื่อนำไปแก้ไขหรือใช้ต่อ

- ใช้ฟอนต์ TH SarabunPSK 16 pt ตามที่ใช้ในหนังสือราชการ (Word จัดวรรณยุกต์และตัดคำไทยเอง)
- จัดหน้าตามแม่แบบเดียวกับไฟล์ PDF: ระยะขอบ ตราครุฑ ที่/ส่วนราชการ วันที่ เรื่อง เรียน ย่อหน้า ส่วนลงนาม
- ไฟล์ Word สร้างจากข้อความ จึงไม่มีลายมือชื่อ ข้อความสั่งการ/เกษียน หรือลายมือชื่อดิจิทัล ฉบับทางการคือไฟล์ PDF ในระบบ
ไม่ import Django จึงทดสอบแยกได้
"""
from io import BytesIO

from docx import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = "TH SarabunPSK"
SIZE = 16
RED = RGBColor(0xC0, 0x00, 0x00)


def _font(run, size=SIZE, bold=False, color=None):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), FONT)
    size_cs = OxmlElement("w:szCs")
    size_cs.set(qn("w:val"), str(size * 2))
    rpr.append(size_cs)
    if bold:
        rpr.append(OxmlElement("w:bCs"))
    lang = OxmlElement("w:lang")
    lang.set(qn("w:bidi"), "th-TH")
    rpr.append(lang)
    return run


class _Builder:
    def __init__(self, spec, number_text, date_text):
        self.spec, self.number, self.date = spec, number_text, date_text
        self.doc = DocxDocument()
        section = self.doc.sections[0]
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.top_margin, section.bottom_margin = Cm(1.5), Cm(2)
        section.left_margin, section.right_margin = Cm(3), Cm(2)
        section.header_distance = section.footer_distance = Cm(0.8)
        style = self.doc.styles["Normal"]
        style.paragraph_format.space_after = Pt(0)
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.line_spacing = 1.0
        _font_style(style)
        if spec.secrecy:
            for part in (section.header, section.footer):
                p = part.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _font(p.add_run(spec.secrecy), 20, True, RED)

    # ----- ตัวช่วย
    def para(self, text="", *, bold=False, size=SIZE, align=None, left=None, first=None, before=0, color=None):
        p = self.doc.add_paragraph()
        fmt = p.paragraph_format
        if align is not None:
            p.alignment = align
        if left is not None:
            fmt.left_indent = Cm(left)
        if first is not None:
            fmt.first_line_indent = Cm(first)
        if before:
            fmt.space_before = Pt(before)
        if text:
            _font(p.add_run(text), size, bold, color)
        return p

    def labelled(self, label, value, hang=1.5, bold_label=False, before=0):
        """ป้ายกำกับ + tab แล้วข้อความแบบย่อหน้าแขวน เช่น "เรื่อง  ขอ..." """
        p = self.para(left=hang, first=-hang, before=before)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(hang), WD_TAB_ALIGNMENT.LEFT)
        _font(p.add_run(label), bold=bold_label)
        _font(p.add_run("\t" + value))
        return p

    def emblem(self, height_cm, align=WD_ALIGN_PARAGRAPH.CENTER):
        p = self.para(align=align)
        if self.spec.emblem_png:
            p.add_run().add_picture(BytesIO(self.spec.emblem_png), height=Cm(height_cm))
        else:
            p.paragraph_format.space_after = Pt(height_cm * 28.35 - 20)  # เว้นที่ให้ตราครุฑ
        return p

    def body(self):
        for text in self.spec.body:
            p = self.para(text, first=2.5, align=WD_ALIGN_PARAGRAPH.THAI_JUSTIFY)
            p.paragraph_format.space_after = Pt(6)

    def signature(self, closing=""):
        # จัดกึ่งกลางที่แกนประมาณ 9.5 ซม. จากขอบซ้าย ตรงกับไฟล์ PDF
        if closing:
            self.para(closing, align=WD_ALIGN_PARAGRAPH.CENTER, left=3, before=12)
        for _ in range(3):
            self.para()
        if self.spec.signer_name:
            self.para(f"({self.spec.signer_name})", align=WD_ALIGN_PARAGRAPH.CENTER, left=3)
        for line in self.spec.signer_position:
            self.para(line, align=WD_ALIGN_PARAGRAPH.CENTER, left=3)

    def urgency(self):
        if self.spec.urgency:
            self.para(self.spec.urgency, bold=True, size=20, color=RED)

    def output(self):
        out = BytesIO()
        self.doc.save(out)
        return out.getvalue()


def _font_style(style):
    style.font.name = FONT
    style.font.size = Pt(SIZE)
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), FONT)
    size_cs = OxmlElement("w:szCs")
    size_cs.set(qn("w:val"), str(SIZE * 2))
    rpr.append(size_cs)


def _no_borders(table):
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "nil")
        borders.append(element)
    table._tbl.tblPr.append(borders)


def _cell_text(cell, lines, *, bold=False, size=SIZE, align=None):
    cell.paragraphs[0].text = ""
    for index, line in enumerate(lines):
        p = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
        if align is not None:
            p.alignment = align
        _font(p.add_run(line), size, bold)


def _outgoing(b):
    s = b.spec
    b.urgency()
    b.emblem(3)
    table = b.doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    _no_borders(table)
    left, right = table.rows[0].cells
    left.width, right.width = Cm(9), Cm(7)
    _cell_text(left, [f"ที่ {b.number}".rstrip()])
    _cell_text(right, [s.org_name, *s.org_address])
    b.para(b.date or " ", left=8, before=8)
    b.labelled("เรื่อง", s.subject, before=8)
    b.labelled("เรียน", s.recipient, before=6)
    if s.reference:
        b.labelled("อ้างถึง", s.reference, hang=1.5, before=6)
    if s.enclosures:
        items = s.enclosures if len(s.enclosures) == 1 else [f"{i}. {t}" for i, t in enumerate(s.enclosures, 1)]
        b.labelled("สิ่งที่ส่งมาด้วย", items[0], hang=2.75, before=6)
        for item in items[1:]:
            b.para(item, left=2.75)
    b.para(before=6)
    b.body()
    b.signature(s.closing or "ขอแสดงความนับถือ")
    if s.contact:
        b.para()
        b.para()
        for line in s.contact:
            b.para(line)


def _internal(b):
    s = b.spec
    b.urgency()
    table = b.doc.add_table(rows=1, cols=2)
    _no_borders(table)
    left, right = table.rows[0].cells
    left.width, right.width = Cm(3), Cm(13)
    if s.emblem_png:
        left.paragraphs[0].add_run().add_picture(BytesIO(s.emblem_png), height=Cm(1.5))
    _cell_text(right, ["บันทึกข้อความ"], bold=True, size=29, align=WD_ALIGN_PARAGRAPH.CENTER)
    b.labelled("ส่วนราชการ", s.department_line or s.org_name, hang=2.25, bold_label=True, before=6)
    p = b.para()
    p.paragraph_format.tab_stops.add_tab_stop(Cm(8), WD_TAB_ALIGNMENT.LEFT)
    _font(p.add_run("ที่"), bold=True)
    _font(p.add_run(f" {b.number}\t"))
    _font(p.add_run("วันที่"), bold=True)
    _font(p.add_run(f" {b.date}"))
    b.labelled("เรื่อง", s.subject, bold_label=True)
    b.labelled("เรียน", s.recipient, before=10)
    b.para(before=4)
    b.body()
    b.signature()


def _order_like(b, title, date_label, numbered):
    s = b.spec
    b.urgency()
    b.emblem(3)
    center = WD_ALIGN_PARAGRAPH.CENTER
    b.para(f"{title}{s.org_name}", bold=True, align=center)
    if numbered:
        b.para(f"ที่ {b.number}".rstrip(), bold=True, align=center)
    b.para(f"เรื่อง  {s.subject}", bold=True, align=center)
    b.para("-" * 30, align=center)
    b.body()
    b.para(f"{date_label} {b.date}".rstrip(), left=6.5, before=12)
    b.signature()


BUILDERS = {
    "OUTGOING": _outgoing,
    "INTERNAL": _internal,
    "ORDER": lambda b: _order_like(b, "คำสั่ง", "สั่ง ณ วันที่", True),
    "ANNOUNCE": lambda b: _order_like(b, "ประกาศ", "ประกาศ ณ วันที่", False),
}


def build_docx(spec, *, number_text="", date_text=""):
    """spec คือ layout.LetterSpec  number_text/date_text ว่างได้ (ยังไม่ออกเลข)"""
    builder = _Builder(spec, number_text, date_text)
    BUILDERS[spec.kind](builder)
    return builder.output()
