from django.db import transaction

from apps.registry.services import issue_number

from . import storage
from .models import Attachment, Document, DocumentEvent, DocumentKind


def log_event(document, user, action, ip=None, **detail):
    """ประวัติของเอกสาร และบันทึกลง Audit Log ของระบบในคราวเดียว"""
    from apps.audit import services as audit

    event = DocumentEvent.objects.create(
        document=document, actor=user if user and user.is_authenticated else None,
        action=action, ip_address=ip or None, detail=detail,
    )
    audit.record(
        "DOCUMENT", action, audit.document_summary(document, event.get_action_display()),
        actor=user, target=document, ip=ip, **detail,
    )
    return event


def register_incoming(*, book, data, main_file, extra_files, user, ip=None):
    """
    ลงทะเบียนหนังสือรับ: สร้างเอกสาร ออกเลขรับ และเก็บไฟล์ในขั้นตอนเดียว
    ถ้าขั้นใดล้มเหลว ทุกอย่างย้อนกลับ (เลขรับที่ยังไม่ได้ commit จะไม่ถูกใช้ เลขจึงไม่ข้าม)

    main_file / extra_files เป็น tuple (ชื่อไฟล์, bytes, จำนวนหน้า) ที่ผ่านการตรวจแล้ว
    """
    written = []
    try:
        with transaction.atomic():
            number = issue_number(book, user, subject=data["subject"])
            document = Document.objects.create(kind=DocumentKind.INCOMING, registration=number, created_by=user, **data)
            for index, (name, content, pages) in enumerate([main_file, *extra_files]):
                key, digest = storage.save_encrypted(content)
                written.append(key)
                Attachment.objects.create(
                    document=document, original_name=name[:255], storage_key=key, size=len(content),
                    sha256=digest, page_count=pages, is_main=(index == 0), uploaded_by=user,
                )
            log_event(document, user, DocumentEvent.Action.REGISTERED, ip,
                      number=number.display_no, files=1 + len(extra_files))
            notify_incoming(document, user)
    except Exception:
        for key in written:
            storage.remove_quietly(key)
        raise
    return document


def notify_incoming(document, actor):
    """แจ้งผู้เกี่ยวข้องว่ามีหนังสือเข้าใหม่ (ตามบทบาทใน ESARABAN_NOTIFY_INCOMING_ROLES ที่ดูแลกลุ่มงานเจ้าของเรื่อง)"""
    from django.conf import settings

    from apps.notifications.services import notify
    from apps.workflow.services import eligible_users

    roles = [r.strip() for r in settings.ESARABAN_NOTIFY_INCOMING_ROLES.split(",") if r.strip()]
    users = []
    for role in roles:
        if document.owner_department is None and role == "HEAD":
            continue  # ไม่ระบุกลุ่มงาน: ไม่แจ้งหัวหน้าทุกกลุ่มงาน
        users.extend(eligible_users(role, document.owner_department, document.secrecy))
    if not users:
        return
    title = "หนังสือเข้าใหม่"
    if document.urgency:  # ด่วน ด่วนมาก ด่วนที่สุด
        title = f"หนังสือเข้าใหม่ ({document.get_urgency_display()})"
    source = f" · จาก {document.source_org}" if document.source_org else ""
    notify(users, title, body=f"{document.registration.display_no} {document.subject}{source}",
           document=document, exclude=actor)


TRACKED_FIELDS = [
    "subject", "source_doc_no", "source_doc_date", "source_org", "recipient",
    "urgency", "secrecy", "owner_department", "due_date", "note",
]


def update_document(document, form, user, ip=None):
    changed = [f for f in form.changed_data if f in TRACKED_FIELDS]
    with transaction.atomic():
        form.save()
        if changed:
            log_event(document, user, DocumentEvent.Action.UPDATED, ip, fields=changed)
    return changed
