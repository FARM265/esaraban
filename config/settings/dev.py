"""ค่าสำหรับเครื่องพัฒนา (Windows + VS Code) ห้ามใช้บน server จริง"""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# บนเครื่องพัฒนาใช้ http ได้ จึงไม่บังคับ secure cookie
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
