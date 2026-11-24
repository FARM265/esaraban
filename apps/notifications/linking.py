"""
เชื่อมบัญชีผู้ใช้กับ LINE

1. ผู้ใช้กด "เชื่อม LINE" ในระบบ ได้รหัส 8 ตัว ใช้ได้ 10 นาที ครั้งเดียว (เก็บเฉพาะ hash)
2. ผู้ใช้เพิ่มเพื่อนบัญชี LINE ของสำนักงาน แล้วส่งรหัสนั้นในแชต (สแกน QR แล้วกดส่งได้เลย)
3. LINE ส่ง webhook มาที่ระบบ ระบบตรวจลายเซ็นของ LINE แล้วผูก LINE userId กับผู้ใช้

รหัสยาว 8 ตัวจากอักษรและตัวเลข 32 ตัว (ไม่มีตัวที่สับสนง่าย) เดาสุ่มไม่ได้ในเวลา 10 นาที
"""
import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ContactSetting

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_RE = re.compile(r"\b([A-Z2-9]{4})-?([A-Z2-9]{4})\b")
CODE_TTL = timedelta(minutes=10)


def _hash(code):
    return hashlib.sha256(code.encode()).hexdigest()


def setting_for(user):
    setting, _ = ContactSetting.objects.get_or_create(user=user)
    return setting


def new_link_code(user):
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    setting = setting_for(user)
    setting.link_code_hash = _hash(code)
    setting.link_code_expires = timezone.now() + CODE_TTL
    setting.save(update_fields=["link_code_hash", "link_code_expires"])
    return f"{code[:4]}-{code[4:]}"


def valid_signature(body, signature):
    if not settings.LINE_CHANNEL_SECRET or not signature:
        return False
    digest = hmac.new(settings.LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


@transaction.atomic
def link_by_code(text, line_user_id):
    """คืนผู้ใช้ที่เชื่อมสำเร็จ หรือ None ถ้ารหัสไม่ถูกต้อง/หมดอายุ"""
    match = CODE_RE.search((text or "").upper())
    if not match or not line_user_id:
        return None
    code_hash = _hash(match.group(1) + match.group(2))
    setting = (
        ContactSetting.objects.select_for_update().select_related("user")
        .filter(link_code_hash=code_hash, link_code_expires__gt=timezone.now(), user__is_active=True).first()
    )
    if setting is None:
        return None
    # LINE หนึ่งบัญชีผูกกับผู้ใช้ได้คนเดียว
    ContactSetting.objects.filter(line_user_id=line_user_id).exclude(pk=setting.pk).update(
        line_user_id="", line_enabled=False, line_linked_at=None
    )
    setting.line_user_id = line_user_id
    setting.line_enabled = True
    setting.line_linked_at = timezone.now()
    setting.link_code_hash = ""
    setting.link_code_expires = None
    setting.save()
    return setting.user


def unlink(user):
    setting = setting_for(user)
    setting.line_user_id = ""
    setting.line_enabled = False
    setting.line_linked_at = None
    setting.save(update_fields=["line_user_id", "line_enabled", "line_linked_at"])
