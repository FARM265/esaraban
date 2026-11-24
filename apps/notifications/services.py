"""สร้างการแจ้งเตือน ส่งเฉพาะผู้ใช้ที่ยังใช้งานอยู่และมีสิทธิ์เห็นเอกสาร ไม่แจ้งผู้ที่ทำรายการเอง"""
from django.urls import reverse
from django.utils import timezone

from .models import Notification

MAX_RECIPIENTS = 200


def notify(users, title, *, body="", document=None, url="", exclude=None):
    from apps.documents import access

    if document is not None and not url:
        url = reverse("documents:detail", args=[document.pk])
    created, seen = [], set()
    for user in users:
        if user is None or user.pk in seen or not user.is_active:
            continue
        seen.add(user.pk)
        if exclude is not None and user.pk == exclude.pk:
            continue
        if document is not None and not access.can_view(user, document):
            continue
        created.append(Notification(
            user=user, title=title[:200], body=(body or "")[:500], url=url[:300], document=document,
        ))
        if len(created) >= MAX_RECIPIENTS:
            break
    created = Notification.objects.bulk_create(created)
    from . import channels

    channels.schedule([n.pk for n in created])  # อีเมล / LINE สำหรับผู้ที่เปิดไว้
    return created


def unread_count(user):
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def mark_read(queryset):
    return queryset.filter(read_at__isnull=True).update(read_at=timezone.now())


def safe_url(url):
    """เปิดได้เฉพาะลิงก์ภายในระบบ กัน open redirect"""
    return url if url.startswith("/") and not url.startswith("//") and "\\" not in url else reverse("notifications:index")
