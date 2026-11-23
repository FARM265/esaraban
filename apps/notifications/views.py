from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
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
