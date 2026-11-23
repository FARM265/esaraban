from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.permissions import capability_required, has_capability
from apps.accounts.security import client_ip

from . import services
from .forms import IssueNumberForm, RegisterBookForm, VoidNumberForm
from .models import IssuedNumber, RegisterBook, RegisterType


def _book_url(book, year=None):
    url = reverse("registry:index") + f"?book={book.pk}"
    return url + (f"&year={year}" if year else "")


@capability_required("view_registry")
def index(request):
    books = list(RegisterBook.objects.all())
    if not books:
        return render(request, "registry/index.html", {"books": []})
    selected = next((b for b in books if str(b.pk) == request.GET.get("book")), books[0])
    year = request.GET.get("year", "")
    year_be = int(year) if year.isdigit() else services.current_year_be()
    years = sorted(
        set(IssuedNumber.objects.filter(book=selected).values_list("year_be", flat=True)) | {services.current_year_be()},
        reverse=True,
    )
    numbers = IssuedNumber.objects.filter(book=selected, year_be=year_be).select_related(
        "issued_by", "voided_by", "document"
    )
    can_register = has_capability(request.user, "register_documents")
    return render(
        request,
        "registry/index.html",
        {
            "books": books,
            "book": selected,
            "year_be": year_be,
            "years": years,
            "page": Paginator(numbers, 50).get_page(request.GET.get("page")),
            "next_number": services.peek_next_number(selected),
            "can_register": can_register,
            "can_issue": can_register and selected.is_active and selected.register_type != RegisterType.RECEIVE,
            "can_manage": has_capability(request.user, "manage_registers"),
            "issue_form": IssueNumberForm(),
            "void_form": VoidNumberForm(),
        },
    )


@capability_required("register_documents")
@require_POST
def issue(request, book_id):
    book = get_object_or_404(RegisterBook, pk=book_id)
    form = IssueNumberForm(request.POST)
    if book.register_type == RegisterType.RECEIVE:
        messages.error(request, "เลขรับออกจากหน้าลงทะเบียนรับเท่านั้น")
    elif form.is_valid():
        try:
            number = services.issue_number(
                book, request.user, subject=form.cleaned_data["subject"], recipient=form.cleaned_data["recipient"]
            )
            messages.success(request, f"ออกเลข {number.display_no} แล้ว")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    else:
        messages.error(request, "กรุณากรอกเรื่อง")
    return redirect(_book_url(book))


@capability_required("register_documents")
@require_POST
def void(request, number_id):
    issued = get_object_or_404(IssuedNumber.objects.select_related("book"), pk=number_id)
    form = VoidNumberForm(request.POST)
    if not form.is_valid():
        messages.error(request, "ต้องระบุเหตุผลการยกเลิกเลข")
        return redirect(_book_url(issued.book, issued.year_be))
    try:
        with transaction.atomic():
            services.void_number(issued, request.user, form.cleaned_data["reason"])
            document = getattr(issued, "document", None)
            if document is not None:
                # เลขรับของเอกสารถูกยกเลิก เอกสารนั้นจึงถูกยกเลิกด้วย (ข้อมูลยังอยู่ครบ)
                from apps.documents.models import DocumentEvent, DocumentStatus
                from apps.documents.services import log_event

                document.status = DocumentStatus.CANCELLED
                document.save(update_fields=["status", "updated_at"])
                log_event(document, request.user, DocumentEvent.Action.CANCELLED, client_ip(request),
                          reason=form.cleaned_data["reason"], number=issued.display_no)
        messages.success(request, f"ยกเลิกเลข {issued.display_no} แล้ว")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect(_book_url(issued.book, issued.year_be))


@capability_required("manage_registers")
def book_edit(request, pk=None):
    instance = get_object_or_404(RegisterBook, pk=pk) if pk else None
    form = RegisterBookForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        book = form.save()
        messages.success(request, f"บันทึกชุดทะเบียน {book.name_th} แล้ว")
        return redirect(_book_url(book))
    preview = services.peek_next_number(instance) if instance else None
    return render(request, "registry/book_form.html", {"form": form, "instance": instance, "preview": preview})
