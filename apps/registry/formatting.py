"""
รูปแบบเลขหนังสือ เช่น "{org}/{no}" -> "ปช XXXX/389"  หรือ "{no}/{year}" -> "1524/2569"

รับเฉพาะตัวแปร org, no, year เท่านั้น และไม่ยอมให้เข้าถึง attribute/index
เพื่อกันการใส่รูปแบบที่ดึงข้อมูลภายในของ Python ออกมา
ไฟล์นี้ไม่ import Django model จึงทดสอบแยกได้
"""
import re
import string

from django.core.exceptions import ValidationError

ALLOWED_FIELDS = {"org", "no", "year"}
_SPEC_RE = re.compile(r"^0?\d{0,2}d?$")  # เช่น "", "04d", "4", "05"


def _check(fmt):
    has_no = False
    try:
        parsed = list(string.Formatter().parse(fmt))
    except ValueError as exc:
        raise ValidationError(f"รูปแบบไม่ถูกต้อง: {exc}") from exc
    for _literal, field, spec, conversion in parsed:
        if field is None:
            continue
        if field not in ALLOWED_FIELDS:
            raise ValidationError(f"ใช้ได้เฉพาะ {{org}} {{no}} {{year}} แต่พบ {{{field}}}")
        if conversion:
            raise ValidationError("ไม่รองรับ !r หรือ !s ในรูปแบบเลข")
        if spec and (field != "no" or not _SPEC_RE.match(spec)):
            raise ValidationError("กำหนดจำนวนหลักได้เฉพาะ {no} เช่น {no:04d}")
        if field == "no":
            has_no = True
    if not has_no:
        raise ValidationError("รูปแบบเลขต้องมี {no}")


def validate_number_format(fmt):
    _check(fmt)
    render_number(fmt, org="ปช XXXX", no=1, year=2569)  # ลองสร้างจริงเพื่อให้แน่ใจว่าไม่ error


def render_number(fmt, org, no, year):
    try:
        return fmt.format(org=org, no=int(no), year=int(year))
    except (KeyError, ValueError, IndexError) as exc:
        raise ValidationError(f"รูปแบบไม่ถูกต้อง: {exc}") from exc
