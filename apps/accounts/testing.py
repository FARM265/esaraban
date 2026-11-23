"""ตัวช่วยสำหรับเทสต์ของทุกโมดูล"""
from django.contrib.auth import get_user_model

from apps.core.constants import RoleCode

from .flow import MFA_VERIFIED
from .models import Role, UserRole

PASSWORD = "Test-Passw0rd-Long!"


def make_user(username, roles=(), **extra):
    """
    สร้างผู้ใช้พร้อมบทบาท แต่ละบทบาทเป็น RoleCode (ทั้งสำนักงาน) หรือ (RoleCode, Department)
    ฟิลด์อื่นของผู้ใช้ (เช่น department=) ส่งผ่าน extra
    """
    user = get_user_model().objects.create_user(username, password=PASSWORD, **extra)
    for item in roles:
        code, dept = item if isinstance(item, tuple) else (item, None)
        UserRole.objects.create(user=user, role=Role.objects.get(code=code), department=dept)
    return user


def make_admin(username="admin"):
    return make_user(username, roles=[RoleCode.ADMIN])


def login_verified(client, user):
    """เข้าสู่ระบบแบบผ่าน MFA แล้ว (ข้ามหน้าจอ ใช้ในเทสต์ที่ไม่ได้ทดสอบการเข้าสู่ระบบเอง)"""
    client.force_login(user)
    session = client.session
    session[MFA_VERIFIED] = True
    session.save()
