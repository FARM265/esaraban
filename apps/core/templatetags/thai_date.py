"""
แสดงวันที่แบบไทย ปี พ.ศ. ตามที่ใช้ในหนังสือราชการ

ใช้ใน template:
    {% load thai_date %}
    {{ doc.created_at|thai_date }}          -> 20 พ.ย. 2569
    {{ doc.created_at|thai_date:"full" }}   -> 20 พฤศจิกายน 2569
    {{ doc.created_at|thai_datetime }}      -> 20 พ.ย. 2569 09:12 น.
"""
from datetime import date, datetime

from django import template
from django.utils import timezone

register = template.Library()

MONTHS_SHORT = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
MONTHS_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
               "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def buddhist_year(value):
    return value.year + 543


def _local(value):
    if isinstance(value, datetime) and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


@register.filter
def thai_date(value, style="short"):
    if not isinstance(value, (date, datetime)):
        return ""
    value = _local(value)
    months = MONTHS_FULL if style == "full" else MONTHS_SHORT
    return f"{value.day} {months[value.month - 1]} {buddhist_year(value)}"


@register.filter
def thai_datetime(value):
    if not isinstance(value, datetime):
        return thai_date(value)
    value = _local(value)
    return f"{thai_date(value)} {value:%H:%M} น."
