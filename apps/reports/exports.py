"""
ส่งออกตารางรายงานเป็น Excel (.xlsx) หรือ PDF (A4 แนวนอน)  ไม่ import Django จึงทดสอบแยกได้

columns = [(หัวคอลัมน์, น้ำหนักความกว้าง), ...]   rows = [[ข้อความ, ...], ...]
PDF ใช้ Typesetter ของหนังสือจากแม่แบบ (จัดวรรณยุกต์ไทยถูกต้อง ตัดคำด้วย libthai และค้นหาข้อความในไฟล์ได้)
"""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from apps.letters import layout

NAVY = "133A6B"
XLSX_FONT = "TH SarabunPSK"


def to_xlsx(title, subtitle, columns, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    width = len(columns)
    ws.append([title])
    ws.append([subtitle])
    ws.append([])
    ws.append([label for label, _ in columns])
    for row in rows:
        ws.append(["" if value is None else value for value in row])
        for cell in ws[ws.max_row]:
            # openpyxl ถือว่าข้อความที่ขึ้นต้นด้วย "=" เป็นสูตร ผู้ใช้จึงอาจใส่สูตรอันตรายในชื่อเรื่องได้ (formula injection)
            if cell.data_type == "f":
                cell.data_type = "s"
    for cell_row in (1, 2):
        ws.merge_cells(start_row=cell_row, start_column=1, end_row=cell_row, end_column=width)
    ws["A1"].font = Font(name=XLSX_FONT, size=18, bold=True, color=NAVY)
    ws["A2"].font = Font(name=XLSX_FONT, size=14, color="51607A")
    thin = Side(style="thin", color="D9E1EC")
    for cell in ws[4]:
        cell.font = Font(name=XLSX_FONT, size=14, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    for row in ws.iter_rows(min_row=5, max_row=ws.max_row):
        for cell in row:
            cell.font = Font(name=XLSX_FONT, size=14)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    total = sum(weight for _, weight in columns)
    for index, (_, weight) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = max(8, round(150 * weight / total))
    ws.freeze_panes = "A5"
    if rows:
        ws.auto_filter.ref = f"A4:{get_column_letter(width)}{ws.max_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "4:4"
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


SIZE = 11
LH = 15
PAD = 4
MARGIN = 36


def to_pdf(title, subtitle, columns, rows, *, regular_font, bold_font=None, footer=""):
    page_w, page_h = landscape(A4)
    ts = layout.Typesetter(regular_font, bold_font)
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h), pageCompression=1)
    c.setTitle(title)
    c.setCreator("E-Saraban (ระบบทดลอง)")
    usable = page_w - 2 * MARGIN
    total = sum(weight for _, weight in columns)
    widths = [usable * weight / total for _, weight in columns]
    xs = [MARGIN + sum(widths[:i]) for i in range(len(widths))]
    state = {"page": 0, "y": 0}

    # Typesetter วัดตำแหน่งจากมุมซ้ายบนของหน้า A4 แนวตั้ง จึงแปลงพิกัดให้เป็นหน้าแนวนอนตรงนี้
    def draw(x, top, text, size=SIZE, bold=False, color="#000000"):
        if not text.strip():
            return
        image, dx, dy, w, h = ts.render_image(text, size, bold, color)
        baseline = top + size
        c.drawImage(ImageReader(image), x + dx, page_h - baseline - (dy + h), width=w, height=h, mask="auto")
        name = ts.pdf_font[bold]
        natural = pdfmetrics.stringWidth(text, name, size)
        t = c.beginText(x, page_h - baseline)
        t.setTextRenderMode(3)
        t.setFont(name, size)
        if natural:
            t.setHorizScale(max(10, min(400, ts.width(text, size, bold) / natural * 100)))
        t.textOut(text)
        c.drawText(t)

    def line(y):
        c.setStrokeColorRGB(0.85, 0.88, 0.93)
        c.setLineWidth(0.6)
        c.line(MARGIN, page_h - y, page_w - MARGIN, page_h - y)

    def header_row():
        lines = [ts.wrap(label, SIZE, w - 2 * PAD, bold=True) for (label, _), w in zip(columns, widths)]
        height = max(len(x) for x in lines) * LH + 2 * PAD
        c.setFillColorRGB(0.075, 0.227, 0.42)
        c.rect(MARGIN, page_h - state["y"] - height, usable, height, stroke=0, fill=1)
        for x, cell in zip(xs, lines):
            for i, text in enumerate(cell):
                draw(x + PAD, state["y"] + PAD + i * LH, text, bold=True, color="#FFFFFF")
        state["y"] += height

    def new_page():
        if state["page"]:
            c.showPage()
        state["page"] += 1
        state["y"] = MARGIN
        if state["page"] == 1:
            draw(MARGIN, state["y"], title, 16, True, "#133A6B")
            state["y"] += 24
            draw(MARGIN, state["y"], subtitle, SIZE, False, "#51607A")
            state["y"] += 22
        draw(page_w - MARGIN - 60, page_h - MARGIN + 6, f"หน้า {state['page']}", 9, False, "#51607A")
        if footer:
            draw(MARGIN, page_h - MARGIN + 6, footer, 9, False, "#51607A")
        header_row()

    new_page()
    if not rows:
        draw(MARGIN + PAD, state["y"] + PAD, "ไม่มีข้อมูลในช่วงที่เลือก", SIZE, False, "#51607A")
    for row in rows:
        cells = [ts.wrap(str(value or ""), SIZE, w - 2 * PAD) for value, w in zip(row, widths)]
        height = max(len(x) for x in cells) * LH + 2 * PAD
        if state["y"] + height > page_h - MARGIN - 14:
            new_page()
        for x, cell in zip(xs, cells):
            for i, text in enumerate(cell):
                draw(x + PAD, state["y"] + PAD + i * LH, text)
        state["y"] += height
        line(state["y"])
    c.save()
    return buf.getvalue()
