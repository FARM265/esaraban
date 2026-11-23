"""
ค่าสำหรับ server จริง ใช้หลัง Nginx ที่ทำ HTTPS
ตั้ง DJANGO_SETTINGS_MODULE=config.settings.prod บน server
"""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import RENDER_EXTERNAL_HOSTNAME, SECRET_KEY, env

DEBUG = False

if SECRET_KEY in ("", "change-me") or len(SECRET_KEY) < 40:
    raise ImproperlyConfigured("SECRET_KEY ไม่ปลอดภัย กรุณาสร้างค่าใหม่ที่ยาวอย่างน้อย 40 ตัวอักษร")

# HTTPS
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]  # Docker healthcheck เรียกภายในด้วย http
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

# Cookie ส่งผ่าน HTTPS เท่านั้น
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if RENDER_EXTERNAL_HOSTNAME:  # บน Render
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{RENDER_EXTERNAL_HOSTNAME}"]

# security.W021 (HSTS preload): ไม่เปิดโดยตั้งใจ ชื่อ server ภายในหน่วยงานไม่ควรอยู่ในรายการ preload สาธารณะของเบราว์เซอร์
SILENCED_SYSTEM_CHECKS = ["security.W021"]

# ผู้ใช้ฐานข้อมูลแบบจำกัดสิทธิ์ (แนะนำสำหรับใช้งานจริง ดู docs/security-checklist.md)
# ถ้าตั้ง POSTGRES_APP_USER ระบบขณะทำงานจะเชื่อมต่อด้วยผู้ใช้นี้ ส่วน migrate ใช้ POSTGRES_USER (entrypoint ตั้ง DJANGO_DB_OWNER=1)
if env.str("POSTGRES_APP_USER", default="") and not env.bool("DJANGO_DB_OWNER", default=False):
    from .base import DATABASES

    DATABASES["default"]["USER"] = env.str("POSTGRES_APP_USER")
    DATABASES["default"]["PASSWORD"] = env.str("POSTGRES_APP_PASSWORD")
