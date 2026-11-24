"""
ส่งการแจ้งเตือนออกนอกระบบ: อีเมล (SMTP หรือ Brevo API) และ LINE (Messaging API)

- ส่งเฉพาะผู้ใช้ที่เปิดช่องทางนั้นเองที่หน้า "ตั้งค่าการแจ้งเตือน"
- หนังสือที่มีชั้นความลับ ไม่ส่งชื่อเรื่องออกไป บอกเพียงว่ามีเรื่องให้เปิดดูในระบบ
  (ข้อความผ่านผู้ให้บริการภายนอก จึงส่งเท่าที่จำเป็น)
- ส่งหลัง transaction สำเร็จ ใน thread แยก หน้าเว็บไม่ต้องรอ ถ้าส่งไม่สำเร็จบันทึกไว้ให้ผู้ใช้เห็น ไม่ทำให้งานหลักล้ม
"""
import json
import logging
import threading
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail import send_mail
from django.db import close_old_connections, transaction
from django.utils import timezone

from apps.core.constants import SecrecyLevel

logger = logging.getLogger("esaraban.notify")

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
TIMEOUT = 15


# ---------------------------------------------------------------------------
# สถานะการตั้งค่า
# ---------------------------------------------------------------------------


def email_ready():
    backend = settings.NOTIFY_EMAIL_BACKEND
    if backend == "smtp":
        return bool(settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD and _sender())
    if backend == "brevo":
        return bool(settings.BREVO_API_KEY and _sender())
    return False


def line_ready():
    return bool(settings.LINE_CHANNEL_ACCESS_TOKEN and settings.LINE_CHANNEL_SECRET and settings.LINE_OA_ID)


def _sender():
    return settings.NOTIFY_EMAIL_FROM or settings.EMAIL_HOST_USER


# ---------------------------------------------------------------------------
# เนื้อหาข้อความ
# ---------------------------------------------------------------------------


def site_link(url):
    base = settings.ESARABAN_SITE_URL.rstrip("/")
    if not base or not url:
        return ""
    return base + url if url.startswith("/") else ""


def message_for(notification):
    """คืนค่า (หัวเรื่อง, เนื้อความ) ที่ปลอดภัยพอจะส่งออกนอกระบบ"""
    document = notification.document
    if document is not None and document.secrecy > SecrecyLevel.NORMAL:
        detail = f"(หนังสือชั้น{document.get_secrecy_display()} เปิดอ่านรายละเอียดในระบบ)"
    else:
        detail = notification.body
    link = site_link(notification.url)
    lines = [notification.title]
    if detail:
        lines.append(detail)
    lines.append(f"เปิดดู: {link}" if link else "เปิดดูในระบบสารบรรณอิเล็กทรอนิกส์")
    return f"[E-Saraban] {notification.title}", "\n".join(lines)


# ---------------------------------------------------------------------------
# ผู้ส่ง
# ---------------------------------------------------------------------------


def _post_json(url, payload, headers):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (URL คงที่ https เท่านั้น)
            return response.status
    except urllib.error.HTTPError as exc:
        body = exc.read(300).decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from None


def send_email(to, subject, text):
    backend = settings.NOTIFY_EMAIL_BACKEND
    if backend == "brevo":
        _post_json(BREVO_URL, {
            "sender": {"name": settings.NOTIFY_EMAIL_FROM_NAME, "email": _sender()},
            "to": [{"email": to}],
            "subject": subject,
            "textContent": text,
        }, {"api-key": settings.BREVO_API_KEY, "Accept": "application/json"})
    elif backend == "smtp":
        send_mail(subject, text, f"{settings.NOTIFY_EMAIL_FROM_NAME} <{_sender()}>", [to], fail_silently=False)
    else:
        raise RuntimeError("ยังไม่ได้ตั้งค่าการส่งอีเมลของระบบ")


def _line_headers():
    return {"Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}"}


def send_line(line_user_id, text):
    _post_json(LINE_PUSH_URL, {"to": line_user_id, "messages": [{"type": "text", "text": text[:4900]}]}, _line_headers())


def reply_line(reply_token, text):
    """ตอบกลับข้อความที่ผู้ใช้ส่งมา (ไม่นับโควตาข้อความของบัญชี)"""
    _post_json(LINE_REPLY_URL, {"replyToken": reply_token, "messages": [{"type": "text", "text": text[:4900]}]},
               _line_headers())


# ---------------------------------------------------------------------------
# ส่งตามการแจ้งเตือนในระบบ
# ---------------------------------------------------------------------------


def _record_error(setting, channel, exc):
    setting.last_error = f"{channel}: {exc}"[:300]
    setting.last_error_at = timezone.now()
    setting.save(update_fields=["last_error", "last_error_at"])
    logger.warning("ส่งแจ้งเตือนทาง %s ให้ %s ไม่สำเร็จ: %s", channel, setting.user_id, exc)


def deliver(notification_ids):
    from .models import ContactSetting, Notification

    use_email, use_line = email_ready(), line_ready()
    if not (use_email or use_line):
        return
    items = Notification.objects.filter(pk__in=notification_ids).select_related("user", "document")
    settings_by_user = {
        s.user_id: s for s in ContactSetting.objects.filter(user__in={n.user_id for n in items})
    }
    for item in items:
        setting = settings_by_user.get(item.user_id)
        if setting is None or not item.user.is_active:
            continue
        subject, text = message_for(item)
        if use_email and setting.email_enabled and item.user.email:
            try:
                send_email(item.user.email, subject, text)
            except Exception as exc:  # noqa: BLE001 ช่องทางเสริม ห้ามทำให้งานหลักล้ม
                _record_error(setting, "อีเมล", exc)
        if use_line and setting.line_enabled and setting.line_user_id:
            try:
                send_line(setting.line_user_id, text)
            except Exception as exc:  # noqa: BLE001
                _record_error(setting, "LINE", exc)


def _run(notification_ids):
    try:
        deliver(notification_ids)
    except Exception:  # noqa: BLE001
        logger.exception("ส่งแจ้งเตือนนอกระบบไม่สำเร็จ")
    finally:
        close_old_connections()


def schedule(notification_ids):
    """ส่งหลัง transaction สำเร็จ (ถ้ายกเลิก ก็ไม่ส่ง)"""
    ids = [pk for pk in notification_ids if pk]
    if not ids or not (email_ready() or line_ready()):
        return

    def start():
        if settings.NOTIFY_ASYNC:
            threading.Thread(target=_run, args=(ids,), daemon=True, name="esaraban-notify").start()
        else:
            deliver(ids)

    transaction.on_commit(start)
