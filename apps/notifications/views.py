import json
import logging
from urllib.parse import quote

import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.security import client_ip
from apps.audit import services as audit

from . import channels, linking, services
from .models import Notification


def index(request):
    qs = Notification.objects.filter(user=request.user).select_related("document")
    only_unread = request.GET.get("unread") == "1"
    if only_unread:
        qs = qs.filter(read_at__isnull=True)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "notifications/index.html", {"page": page, "only_unread": only_unread})


@require_POST
def open_item(request, pk):
    item = get_object_or_404(Notification, pk=pk, user=request.user)
    services.mark_read(Notification.objects.filter(pk=item.pk))
    return redirect(services.safe_url(item.url))


@require_POST
def mark_all_read(request):
    services.mark_read(Notification.objects.filter(user=request.user))
    return redirect("notifications:index")


# ---------------------------------------------------------------------------
# ตั้งค่าแจ้งเตือนนอกระบบ (อีเมล / LINE)
# ---------------------------------------------------------------------------

logger = logging.getLogger("esaraban.notify")
MAX_WEBHOOK_BYTES = 256 * 1024


def _qr(url):
    return segno.make_qr(url, error="m").svg_data_uri(scale=5, border=2)


def contact_settings(request):
    user = request.user
    setting = linking.setting_for(user)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "email":
            email = request.POST.get("email", "").strip()
            try:
                if email:
                    validate_email(email)
            except ValidationError:
                messages.error(request, "รูปแบบอีเมลไม่ถูกต้อง")
                return redirect("notifications:settings")
            if email != user.email:
                user.email = email
                user.save(update_fields=["email"])
            setting.email_enabled = bool(email) and request.POST.get("email_enabled") == "1"
            setting.save(update_fields=["email_enabled"])
            messages.success(request, "บันทึกการแจ้งเตือนทางอีเมลแล้ว")
        elif action == "line_code":
            request.session["line_link_code"] = linking.new_link_code(user)
            return redirect("notifications:settings")
        elif action == "line_toggle" and setting.line_linked:
            setting.line_enabled = request.POST.get("line_enabled") == "1"
            setting.save(update_fields=["line_enabled"])
            messages.success(request, "บันทึกการแจ้งเตือนทาง LINE แล้ว")
        elif action == "line_unlink":
            linking.unlink(user)
            audit.record("USER", "LINE_UNLINKED", f"ยกเลิกการเชื่อม LINE ของ {user.username}", actor=user,
                         target=user, ip=client_ip(request))
            messages.success(request, "ยกเลิกการเชื่อม LINE แล้ว")
        elif action == "test":
            sent = []
            setting.refresh_from_db()
            text = "ข้อความทดสอบจากระบบสารบรรณอิเล็กทรอนิกส์ ถ้าได้รับข้อความนี้ แปลว่าการแจ้งเตือนใช้งานได้"
            try:
                if channels.email_ready() and setting.email_enabled and user.email:
                    channels.send_email(user.email, "[E-Saraban] ทดสอบการแจ้งเตือน", text)
                    sent.append("อีเมล")
                if channels.line_ready() and setting.line_enabled and setting.line_user_id:
                    channels.send_line(setting.line_user_id, text)
                    sent.append("LINE")
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f"ส่งไม่สำเร็จ: {str(exc)[:200]}")
                return redirect("notifications:settings")
            if sent:
                messages.success(request, f"ส่งข้อความทดสอบทาง{' และ '.join(sent)}แล้ว ตรวจดูได้เลย")
            else:
                messages.warning(request, "ยังไม่ได้เปิดช่องทางใด จึงยังไม่ได้ส่ง")
        return redirect("notifications:settings")

    code = request.session.pop("line_link_code", "")
    oa = settings.LINE_OA_ID
    context = {
        "setting": setting,
        "email_ready": channels.email_ready(),
        "line_ready": channels.line_ready(),
        "link_code": code,
        "line_add_url": f"https://line.me/R/ti/p/{quote(oa)}" if oa else "",
        "line_send_url": f"https://line.me/R/oaMessage/{quote(oa)}/?{quote(code)}" if oa and code else "",
    }
    if context["line_add_url"]:
        context["line_add_qr"] = _qr(context["line_add_url"])
    if context["line_send_url"]:
        context["line_send_qr"] = _qr(context["line_send_url"])
    return render(request, "notifications/settings.html", context)


@login_not_required
@csrf_exempt
@require_POST
def line_webhook(request):
    """รับข้อความจาก LINE: ตรวจลายเซ็นทุกครั้ง แล้วผูกบัญชีเมื่อผู้ใช้ส่งรหัสเชื่อม"""
    if not channels.line_ready():
        return HttpResponse(status=404)
    body = request.body
    if len(body) > MAX_WEBHOOK_BYTES:
        return HttpResponseBadRequest()
    if not linking.valid_signature(body, request.headers.get("X-Line-Signature", "")):
        return HttpResponseForbidden()
    try:
        events = json.loads(body).get("events", [])
    except (ValueError, AttributeError):
        return HttpResponseBadRequest()
    for event in events[:20]:
        source = event.get("source") or {}
        line_user_id = source.get("userId", "")
        token = event.get("replyToken")
        reply = None
        if event.get("type") == "follow":
            reply = ("สวัสดีครับ นี่คือบัญชีแจ้งเตือนของระบบสารบรรณอิเล็กทรอนิกส์\n"
                     "เข้าระบบ > ตั้งค่าการแจ้งเตือน > กด \"เชื่อม LINE\" แล้วส่งรหัส 8 ตัวที่ได้มาในแชตนี้")
        elif event.get("type") == "message" and (event.get("message") or {}).get("type") == "text":
            if source.get("type") != "user":
                continue  # ไม่ผูกบัญชีจากกลุ่มแชต
            user = linking.link_by_code(event["message"].get("text", ""), line_user_id)
            if user is not None:
                audit.record("USER", "LINE_LINKED", f"เชื่อม LINE กับผู้ใช้ {user.username}", actor=user, target=user)
                reply = f"เชื่อมกับบัญชี {user.display_name_th} แล้ว ต่อไปจะได้รับการแจ้งเตือนจากระบบทางแชตนี้"
            else:
                reply = "รหัสไม่ถูกต้องหรือหมดอายุแล้ว กด \"เชื่อม LINE\" ในระบบเพื่อรับรหัสใหม่ (รหัสใช้ได้ 10 นาที)"
        if reply and token:
            try:
                channels.reply_line(token, reply)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ตอบกลับ LINE ไม่สำเร็จ: %s", exc)
    return HttpResponse("ok")
