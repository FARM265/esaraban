import hashlib
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .menu import build_menu


@lru_cache(maxsize=1)
def asset_version():
    """
    รหัสเวอร์ชันของไฟล์ CSS/JS คำนวณจากเนื้อไฟล์ ใช้ต่อท้าย URL (?v=...)
    เมื่อไฟล์เปลี่ยน รหัสเปลี่ยน เบราว์เซอร์จึงโหลดไฟล์ใหม่ทันทีแม้ตั้งให้จำไฟล์ไว้นาน
    """
    digest = hashlib.sha256()
    for root in settings.STATICFILES_DIRS:
        for path in sorted(Path(root).rglob("*")):
            if path.suffix in {".css", ".js"} and path.is_file():
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


def site_context(request):
    return {
        "ORG_NAME": settings.ESARABAN_ORG_NAME,
        "ORG_UNIT": settings.ESARABAN_ORG_UNIT,
        "LOGIN_REQUIRE_MFA": settings.ESARABAN_LOGIN_REQUIRE_MFA,
        "IS_TEST_SYSTEM": settings.ESARABAN_IS_TEST_SYSTEM,
        "ASSET_VERSION": asset_version(),
        "YEAR_BE": timezone.localdate().year + 543,
        "nav_menu": build_menu(request.user, request.path) if hasattr(request, "user") else [],
        "UNREAD_NOTIFICATIONS": _unread(request),
    }


def _unread(request):
    from apps.notifications.services import unread_count

    return unread_count(getattr(request, "user", None))
