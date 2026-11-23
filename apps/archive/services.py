import datetime as dt

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import has_capability
from apps.documents import access
from apps.documents.models import Document, DocumentEvent, DocumentStatus
from apps.documents.services import log_event

from .models import ArchiveRecord

ARCHIVABLE_STATUSES = {DocumentStatus.REGISTERED, DocumentStatus.DONE}


def active_record(document):
    return ArchiveRecord.objects.filter(document=document, released_at__isnull=True).first()


def _running(document):
    from apps.workflow.services import running_instance

    return running_instance(document) is not None


def can_archive(user, document):
    return (
        document.status in ARCHIVABLE_STATUSES
        and not _running(document)
        and access.can_view(user, document)
        and has_capability(user, "archive_documents", document.owner_department)
    )


def can_release(user, document):
    return (
        document.status == DocumentStatus.ARCHIVED
        and access.can_view(user, document)
        and has_capability(user, "archive_documents", document.owner_department)
    )


def keep_until(archived_on, years):
    """นับถึงวันสิ้นปีปฏิทินของปีที่ครบอายุ  years=0 คือเก็บตลอดไป"""
    return None if not years else dt.date(archived_on.year + years, 12, 31)


@transaction.atomic
def archive(document, user, *, folder, retention_years, note="", ip=None):
    document = Document.objects.select_for_update().get(pk=document.pk)
    if not can_archive(user, document):
        raise PermissionDenied
    folder = (folder or "").strip()
    if not folder:
        raise ValidationError("กรุณาระบุหมวด/แฟ้ม")
    now = timezone.now()
    record = ArchiveRecord.objects.create(
        document=document, folder=folder[:200], retention_years=retention_years,
        keep_until=keep_until(timezone.localdate(now), retention_years), note=(note or "").strip(),
        previous_status=document.status, archived_by=user, archived_at=now,
    )
    document.status = DocumentStatus.ARCHIVED
    document.save(update_fields=["status", "updated_at"])
    log_event(document, user, DocumentEvent.Action.ARCHIVED, ip, folder=record.folder,
              retention=record.get_retention_years_display(),
              keep_until=record.keep_until.isoformat() if record.keep_until else "ตลอดไป")
    return record


@transaction.atomic
def release(document, user, *, reason, ip=None):
    document = Document.objects.select_for_update().get(pk=document.pk)
    if not can_release(user, document):
        raise PermissionDenied
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("กรุณาระบุเหตุผลที่นำออกจากคลัง")
    record = active_record(document)
    if record is None:
        raise ValidationError("ไม่พบข้อมูลการจัดเก็บ")
    record.released_by, record.released_at, record.release_reason = user, timezone.now(), reason
    record.save(update_fields=["released_by", "released_at", "release_reason"])
    document.status = record.previous_status or DocumentStatus.DONE
    document.save(update_fields=["status", "updated_at"])
    log_event(document, user, DocumentEvent.Action.UNARCHIVED, ip, folder=record.folder, reason=reason)
    return record


def folders():
    return list(ArchiveRecord.objects.order_by("folder").values_list("folder", flat=True).distinct()[:200])
