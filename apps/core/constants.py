"""ค่าคงที่ที่ใช้ร่วมกันหลายโมดูล ตามระเบียบงานสารบรรณ"""
from django.db import models


class SecrecyLevel(models.IntegerChoices):
    """ชั้นความลับ เรียงจากน้อยไปมาก ใช้เทียบกับระดับสิทธิ์ของผู้ใช้ได้ตรง ๆ"""

    NORMAL = 0, "ปกติ"
    CONFIDENTIAL = 1, "ลับ"
    SECRET = 2, "ลับมาก"
    TOP_SECRET = 3, "ลับที่สุด"


class Urgency(models.IntegerChoices):
    NORMAL = 0, "ปกติ"
    URGENT = 1, "ด่วน"
    VERY_URGENT = 2, "ด่วนมาก"
    MOST_URGENT = 3, "ด่วนที่สุด"


class RoleCode(models.TextChoices):
    """บทบาท 6 แบบตามข้อกำหนด ใช้ในขั้นตอนที่ 5"""

    ADMIN = "ADMIN", "ผู้ดูแลระบบ"
    EXECUTIVE = "EXECUTIVE", "ผู้บริหาร"
    HEAD = "HEAD", "หัวหน้ากลุ่มงาน"
    CLERK = "CLERK", "เจ้าหน้าที่สารบรรณ"
    STAFF = "STAFF", "เจ้าหน้าที่ทั่วไป"
    AUDITOR = "AUDITOR", "ผู้ตรวจสอบ"
