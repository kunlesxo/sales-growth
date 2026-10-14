"""Public pages, the Paystack and Telegram webhooks, the health check and the staff dashboard."""
import hmac
import json
import logging
import re

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import bot
from .models import Enrollment, Payment, TelegramUpdate
from .services import access, paystack

log = logging.getLogger(__name__)
REF_RE = re.compile(r"^[A-Za-z0-9_-]{4,50}$")


def _course_context():
    course = settings.COURSE
    ctx = {
        "course": course,
        "paystack_url": settings.PAYSTACK_PAGE_URL,
        "ngn_label": f"₦{course['price_ngn_kobo'] // 100:,}",
        "ghs_enabled": bool(course["price_ghs_pesewas"]),
        "support_url": settings.SUPPORT_WHATSAPP_URL,
    }
    if ctx["ghs_enabled"]:
        ctx["ghs_label"] = f"GH₵{course['price_ghs_pesewas'] // 100:,}"
    return ctx


@require_GET
def landing(request):
    return render(request, "academy/landing.html", _course_context())


@require_GET
def success(request):
    """Shows success only after Paystack has confirmed the reference. The URL alone proves nothing."""
    ctx = _course_context()
    ref = (request.GET.get("reference") or request.GET.get("trxref") or "").strip()
    ctx["reference"] = ref
    if not REF_RE.match(ref):
        ctx["state"] = "missing"
    else:
        try:
            payment = access.sync_payment(ref)
            ctx["state"] = "verified" if payment and payment.qualifies else "pending"
        except paystack.PaystackError:
            ctx["state"] = "busy"
        ctx["deep_link"] = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={ref}"
    return render(request, "academy/success.html", ctx)


@require_GET
def refund_policy(request):
    return render(request, "academy/refund.html", _course_context())


@require_GET
def health(request):
    return HttpResponse("ok")


@csrf_exempt
@require_POST
def paystack_webhook(request):
    if not paystack.valid_signature(request.body, request.headers.get("x-paystack-signature", "")):
        return HttpResponseForbidden("bad signature")
    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("bad json")
    if event.get("event") == "charge.success":
        ref = str((event.get("data") or {}).get("reference") or "")
        if REF_RE.match(ref):
            try:
                access.sync_payment(ref)
            except paystack.PaystackError:
                return HttpResponse("retry later", status=500)  # Paystack re-sends failed deliveries
    return HttpResponse("ok")


@csrf_exempt
@require_POST
def telegram_webhook(request):
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected or not hmac.compare_digest(got.encode(), expected.encode()):
        return HttpResponseForbidden()
    try:
        update = json.loads(request.body)
        update_id = int(update["update_id"])
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest()
    try:
        TelegramUpdate.objects.create(update_id=update_id)
    except IntegrityError:
        return HttpResponse("duplicate")  # already handled: Telegram re-sent it
    try:
        bot.handle_update(update)
    except Exception:
        log.exception("telegram update %s failed", update_id)
    return HttpResponse("ok")


@staff_member_required
@require_GET
def dashboard(request):
    st = Enrollment.Status
    stats = [
        ("Total paid students", Payment.objects.filter(qualifies=True).count()),
        ("Successful payments", Payment.objects.filter(status="success").count()),
        ("Telegram connected", Enrollment.objects.filter(telegram_user_id__isnull=False).count()),
        ("Not connected yet", Enrollment.objects.filter(telegram_user_id__isnull=True).count()),
        ("Active students", Enrollment.objects.filter(status=st.ACTIVE).count()),
        ("Expired", Enrollment.objects.filter(status=st.EXPIRED).count()),
        ("Revoked", Enrollment.objects.filter(status=st.REVOKED).count()),
    ]
    ctx = {
        **admin.site.each_context(request),
        "stats": stats,
        "recent": Enrollment.objects.select_related("payment")[:25],
    }
    return render(request, "academy/dashboard.html", ctx)
