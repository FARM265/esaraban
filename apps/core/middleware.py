"""
header ความปลอดภัยที่ Django ไม่ได้ใส่ให้

Content-Security-Policy: โหลดสคริปต์/สไตล์/ฟอนต์ได้เฉพาะจาก server นี้ ห้ามสคริปต์ inline ห้ามฝังหน้าในเว็บอื่น
  (ระบบไม่ใช้ CDN ตอนใช้งาน ทุกไฟล์อยู่ใน static/vendor) style อนุญาต inline เพราะหน้าจอใช้ style="..." บางจุด
  img/worker อนุญาต blob: และ data: สำหรับ PDF.js และ QR code ของ MFA
Permissions-Policy: ปิดกล้อง ไมโครโฟน ตำแหน่ง และ API ที่ระบบไม่ใช้
"""
from django.conf import settings

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])
PERMISSIONS = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        header = "Content-Security-Policy-Report-Only" if settings.ESARABAN_CSP_REPORT_ONLY else "Content-Security-Policy"
        response.headers.setdefault(header, CSP)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS)
        return response


class HealthCheckMiddleware:
    """
    ตอบ /healthz ก่อน middleware อื่น โดยไม่ตรวจชื่อโดเมน (ALLOWED_HOSTS) และไม่บังคับ HTTPS
    เพราะระบบเฝ้าระวังของผู้ให้บริการ (เช่น Render) เรียกด้วย IP ภายในซึ่งไม่อยู่ในรายชื่อโดเมน
    ตอบแค่ ok/error ไม่เปิดเผยข้อมูลอื่น
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info == "/healthz":
            from .views import healthz

            return healthz(request)
        return self.get_response(request)
