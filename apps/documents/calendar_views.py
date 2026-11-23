"""
ลงปฏิทินจากไฟล์หนังสือ: ระบบอ่านชื่องาน วันที่ เวลา สถานที่ และเรื่องจากไฟล์ให้ ผู้ใช้ตรวจแก้ แล้วเลือก
- เพิ่มลง Google Calendar: เปิดหน้า Google Calendar ของผู้ใช้เองพร้อมกรอกข้อมูลไว้ ผู้ใช้กดบันทึกที่ Google
  (ระบบไม่เก็บรหัสผ่านหรือสิทธิ์เข้าถึงบัญชี Google ของใคร)
- ดาวน์โหลดไฟล์ .ics: นำเข้าปฏิทินใดก็ได้ (Google, Outlook, iPhone)
หนังสือชั้นความลับส่งไป Google ไม่ได้ ทุกการส่งออกบันทึกใน Audit Log
"""
import io
import uuid

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts.permissions import has_capability
from apps.accounts.security import client_ip
from apps.audit.models import Category
from apps.audit.services import document_summary, record

from . import appointment, pdftext, services, storage
from .calendar_forms import AppointmentForm, CalendarUploadForm
from .models import DocumentEvent
from .views import _get_visible


def can_use_calendar(user):
    """ผู้ที่ทำงานกับหนังสือ (สารบรรณ เจ้าหน้าที่ หัวหน้า ผู้บริหาร) ผู้ดูแลระบบและผู้ตรวจสอบไม่ได้อ่านเนื้อหาหนังสือ"""
    return has_capability(user, "create_documents") or has_capability(user, "register_documents")


def _initial(appt):
    return {
        "title": appt.title, "subject": appt.subject, "start_date": appt.start_date, "end_date": appt.end_date,
        "start_time": appt.start_time, "end_time": appt.end_time, "location": appt.location,
    }


def _from_form(cleaned):
    return appointment.Appointment(
        title=cleaned["title"].strip(), subject=cleaned.get("subject", "").strip(),
        start_date=cleaned["start_date"], end_date=cleaned.get("end_date"),
        start_time=cleaned.get("start_time"), end_time=cleaned.get("end_time"),
        location=cleaned.get("location", "").strip(),
    )


def _details(cleaned, document=None, short=False, link=""):
    """short=True สำหรับลิงก์ Google ซึ่งต้องสั้น: ใส่เฉพาะรายละเอียดที่ผู้ใช้พิมพ์และเลขที่หนังสือ"""
    # ลิงก์กลับมาที่หนังสือในระบบ (เปิดได้เฉพาะผู้มีสิทธิ์ ต้องเข้าสู่ระบบก่อน) ใส่ไว้บรรทัดแรกเพื่อไม่ให้ถูกตัด
    lines = [f"เปิดหนังสือในระบบ: {link}"] if link else []
    if short:
        if cleaned.get("details"):
            lines.append(cleaned["details"].strip())
        if document is not None and document.registration_id:
            lines.append(f"หนังสือ {document.registration.display_no}")
        if cleaned.get("subject") and cleaned["subject"] not in cleaned["title"]:
            lines.append(f"เรื่อง {cleaned['subject']}")
        return "\n".join(lines)
    if cleaned.get("subject"):
        lines.append(f"เรื่อง: {cleaned['subject']}")
    if document is not None:
        number = document.registration.display_no if document.registration_id else "ยังไม่มีเลข"
        lines.append(f"หนังสือ: {document.get_kind_display()} {number}")
    if cleaned.get("details"):
        lines.append(cleaned["details"].strip())
    lines.append(f"บันทึกจากระบบสารบรรณอิเล็กทรอนิกส์ {settings.ESARABAN_ORG_NAME}")
    return "\n".join(lines)


FIELD_LABELS = {"subject": "เรื่อง", "start_date": "วันที่", "start_time": "เวลา", "location": "สถานที่"}


def _completeness(appt):
    return (3 if appt.start_date else 0) + (2 if appt.subject else 0) + (1 if appt.start_time else 0) + (1 if appt.location else 0)


def _read(data, force_ocr=False):
    """
    อ่านไฟล์ด้วยตัวอ่านหลายตัว (pdfium, poppler, pypdf) เลือกผลที่ได้ข้อมูลครบและข้อความสะอาดที่สุด
    ถ้ายังไม่ได้เรื่องหรือวันที่ หรือข้อความเพี้ยน จึงอ่านจากภาพ (OCR) เพิ่ม แล้วเติมช่องที่ยังว่างจากผลอื่น
    """
    versions = [] if force_ocr else pdftext.text_versions(data)
    results = [(v, appointment.extract(v.text, ocr=False)) for v in versions]

    def key(i):
        version, appt = results[i]
        return (-_completeness(appt), -pdftext.quality(version.text), i)

    best_i = min(range(len(results)), key=key) if results else None
    weak = best_i is None or _completeness(results[best_i][1]) < 5 or pdftext.quality(results[best_i][0].text) < 8
    notes = []
    if force_ocr or weak:
        ocr = pdftext.ocr_version(data)
        if ocr is not None:
            results.append((ocr, appointment.extract(ocr.text, ocr=True)))
        elif not results or force_ocr:
            notes.append(pdftext.NO_OCR_NOTE)
    if not results:
        return appointment.Appointment(), notes or ["อ่านข้อความจากไฟล์ไม่ได้ กรุณากรอกข้อมูลเอง"]

    order = sorted(range(len(results)), key=key)
    version, best = results[order[0]]
    for i in order[1:]:
        other = results[i][1]
        if not best.subject and other.subject:
            best.subject, best.title = other.subject, other.title
        if not best.start_date and other.start_date:
            best.start_date, best.end_date, best.snippet = other.start_date, other.end_date, other.snippet
            best.start_time, best.end_time = other.start_time, other.end_time
        if not best.start_time and other.start_time and other.start_date == best.start_date:
            best.start_time, best.end_time = other.start_time, other.end_time
        if not best.location and other.location:
            best.location = other.location
    if version.note:
        notes.append(version.note)
    notes += [n for n in best.notes if n and "ไม่พบวันนัดหมาย" not in n]
    return best, notes


def _missing_note(appt):
    missing = [label for field, label in FIELD_LABELS.items() if not getattr(appt, field)]
    return ["ระบบหาไม่พบในหนังสือ: " + " ".join(missing) + " กรุณากรอกเอง"] if missing else []


def _export(request, form, *, document=None, summary_label):
    """จัดการปุ่มส่งออก คืน response (ไฟล์ .ics) หรือ URL ของ Google Calendar หรือ None ถ้ายังส่งออกไม่ได้"""
    action = request.POST.get("action")
    cleaned = form.cleaned_data
    appt = _from_form(cleaned)
    link = request.build_absolute_uri(reverse("documents:detail", args=[document.pk])) if document is not None else ""
    details = _details(cleaned, document, link=link)
    if document is not None:
        summary = document_summary(document, summary_label)
    else:
        summary = f"{summary_label}: {appt.title}"
    if action == "google":
        if document is not None and document.secrecy:
            form.add_error(None, "หนังสือชั้นความลับส่งข้อมูลไป Google ไม่ได้ ใช้ \"ดาวน์โหลดไฟล์ .ics\" แทน")
            return None
        if form.require_not_secret and not cleaned.get("not_secret"):
            form.add_error("not_secret", "ต้องยืนยันก่อนส่งข้อมูลไป Google")
            return None
        record(Category.DOCUMENT, "CALENDAR_GOOGLE", summary, actor=request.user, target=document,
               ip=client_ip(request), date=str(appt.start_date))
        return appointment.google_url(appt, _details(cleaned, document, short=True, link=link))
    if action == "ics":
        record(Category.DOCUMENT, "CALENDAR_ICS", summary, actor=request.user, target=document,
               ip=client_ip(request), date=str(appt.start_date))
        data = appointment.to_ics(appt, uid=f"{uuid.uuid4()}@esaraban", details=details)
        response = FileResponse(io.BytesIO(data), as_attachment=True, filename="appointment.ics",
                                 content_type="text/calendar; charset=utf-8")
        response["Cache-Control"] = "private, no-store"
        return response
    form.add_error(None, "กรุณาเลือกปุ่มเพิ่มลงปฏิทิน")
    return None


@never_cache
@require_http_methods(["GET", "POST"])
def calendar_from_document(request, pk):
    document = _get_visible(request, pk)
    if not can_use_calendar(request.user):
        raise PermissionDenied
    attachments = list(document.attachments.all())
    if not attachments:
        messages.error(request, "เอกสารนี้ไม่มีไฟล์")
        return redirect("documents:detail", pk=document.pk)
    wanted = request.GET.get("file") or request.POST.get("file")
    attachment = next((a for a in attachments if str(a.pk) == wanted), None) or max(
        attachments, key=lambda a: (a.uploaded_at, a.pk)
    )
    context = {"doc": document, "attachment": attachment, "secret": bool(document.secrecy), "notes": [], "snippet": ""}

    if request.method == "POST":
        context["snippet"] = request.POST.get("snippet", "")[:400]
        form = AppointmentForm(request.POST)
        if form.is_valid():
            outcome = _export(request, form, document=document, summary_label="ลงปฏิทิน")
            if isinstance(outcome, str):
                context["google_url"] = outcome
            elif outcome is not None:
                return outcome
    else:
        data = storage.read_decrypted(attachment.storage_key, attachment.sha256)
        services.log_event(document, request.user, DocumentEvent.Action.VIEWED, client_ip(request),
                           file=attachment.original_name)
        appt, notes = _read(data, force_ocr=request.GET.get("ocr") == "1")
        if not appt.subject and document.subject:
            appt.subject = document.subject  # ใช้เรื่องที่ลงทะเบียนไว้แทน
            appt.title = appt.title or appointment.clean_title(document.subject)
        notes += _missing_note(appt)
        initial = _initial(appt)
        source = " ".join(x for x in (document.source_org, f"ที่ {document.source_doc_no}" if document.source_doc_no else "") if x)
        if source:
            initial["details"] = f"จาก {source}"
        context.update(notes=notes, snippet=appt.snippet, ocr_url=f"?file={attachment.pk}&ocr=1")
        form = AppointmentForm(initial=initial)
    context["form"] = form
    return render(request, "documents/calendar.html", context)


@never_cache
@require_http_methods(["GET", "POST"])
def calendar_upload(request):
    """อัปโหลดไฟล์มาอ่านวันนัดหมายโดยตรง ไฟล์ไม่ถูกเก็บในระบบ"""
    if not can_use_calendar(request.user):
        raise PermissionDenied
    context = {"upload_form": CalendarUploadForm(), "notes": [], "snippet": ""}
    if request.method == "POST" and request.FILES:
        upload_form = CalendarUploadForm(request.POST, request.FILES)
        context["upload_form"] = upload_form
        if upload_form.is_valid():
            appt, notes = _read(upload_form.cleaned_data["file"], force_ocr=upload_form.cleaned_data.get("force_ocr"))
            notes += _missing_note(appt)
            context.update(
                form=AppointmentForm(initial=_initial(appt), require_not_secret=True),
                notes=notes, snippet=appt.snippet, file_name=request.FILES["file"].name,
            )
    elif request.method == "POST":
        form = AppointmentForm(request.POST, require_not_secret=True)
        context.update(form=form, snippet=request.POST.get("snippet", "")[:400])
        if form.is_valid():
            outcome = _export(request, form, summary_label="ลงปฏิทินจากไฟล์ที่อัปโหลด")
            if isinstance(outcome, str):
                context["google_url"] = outcome
            elif outcome is not None:
                return outcome
    return render(request, "documents/calendar.html", context)
