"""Business rules: verified purchase -> Telegram identity -> controlled access -> expiry.

Every write is idempotent. The Paystack reference is the key: one payment gives one enrollment,
and one enrollment is tied to one Telegram account."""
import calendar
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..models import AuditLog, Enrollment, InviteLink, Payment
from . import paystack, telegram
from .telegram import TelegramError

log = logging.getLogger(__name__)

SPACES = ("classroom", "discussion")  # every group the bot can add or remove a student from
JOIN_SPACES = ("discussion",)  # the groups a student is sent a join link for at purchase
MAX_LINKS_PER_DAY = 10
ACTIVE = Enrollment.Status.ACTIVE
REVOKED = Enrollment.Status.REVOKED
EXPIRED = Enrollment.Status.EXPIRED


class LinkLimitReached(Exception):
    pass


def chat_for(space):
    if space == "classroom":
        return settings.CLASSROOM_CHAT_ID
    if space == "discussion":
        return settings.DISCUSSION_CHAT_ID
    raise ValueError(f"no Telegram group for space {space!r}")


def audit(action, reference="", detail=""):
    try:
        AuditLog.objects.create(action=action, reference=reference or "", detail=str(detail)[:2000])
    except Exception:  # logging must never break a purchase
        log.exception("audit write failed")


def add_months(dt, months):
    idx = dt.month - 1 + months
    year, month = dt.year + idx // 12, idx % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def judge(tx):
    """Decide whether a Paystack transaction qualifies for the course. Returns (qualifies, reason)."""
    if tx.get("status") != "success":
        return False, f"status_{tx.get('status')}"[:80]
    course = settings.COURSE
    currency = tx.get("currency")
    if currency == "NGN":
        expected = course["price_ngn_kobo"]
    elif currency == "GHS" and course["price_ghs_pesewas"]:
        expected = course["price_ghs_pesewas"]
    else:
        return False, "currency_not_accepted"
    amount = tx.get("amount") or 0
    if amount < expected:
        return False, "amount_too_low"
    # Paystack passes its fee to the customer, so allow a small margin above the price.
    if amount > expected * (100 + course["tolerance_pct"]) // 100:
        return False, "amount_too_high"
    return True, ""


def sync_payment(reference):
    """Ask Paystack about this reference and store the result. Safe to call any number of times.
    Returns the Payment, or None if Paystack does not know the reference. Raises PaystackError on outage."""
    tx = paystack.verify_transaction(reference)
    if not tx or tx.get("reference") != reference:
        return None
    qualifies, reason = judge(tx)
    cust = tx.get("customer") or {}
    name = " ".join(p for p in (cust.get("first_name"), cust.get("last_name")) if p)
    with transaction.atomic():
        payment, _ = Payment.objects.get_or_create(reference=reference)
        was_qualifying = payment.qualifies
        payment.paystack_id = tx.get("id")
        payment.status = (tx.get("status") or "")[:30]
        payment.amount = tx.get("amount")
        payment.currency = (tx.get("currency") or "")[:8]
        payment.email = (cust.get("email") or "")[:254]
        payment.customer_name = name[:200]
        payment.paid_at = parse_datetime(tx["paid_at"]) if tx.get("paid_at") else None
        payment.qualifies = qualifies
        payment.reject_reason = reason
        payment.last_checked_at = timezone.now()
        payment.save()
        if qualifies:
            _ensure_enrollment(payment)
    if was_qualifying and not qualifies:
        enrollment = Enrollment.objects.filter(payment=payment).first()
        if enrollment and enrollment.status in (ACTIVE, Enrollment.Status.UNLINKED):
            _end(enrollment, REVOKED, f"payment no longer valid: {reason}", reference)
    return payment


def _ensure_enrollment(payment):
    enrollment, created = Enrollment.objects.get_or_create(
        payment=payment,
        defaults={
            "email": payment.email,
            "customer_name": payment.customer_name,
            "purchased_at": payment.paid_at or timezone.now(),
        },
    )
    if created:
        audit("enrollment_created", payment.reference)
    return enrollment


def claim(reference, tg_user):
    """Bind a verified purchase to a Telegram account (called on /start <reference>).
    The first successful claim starts the 12 months. Repeat claims by the same person change nothing.
    Returns (outcome, enrollment). Outcomes: ok, invalid, claimed_by_other, telegram_has_other, revoked, expired."""
    payment = sync_payment(reference)  # always re-check with Paystack, so reversals are caught
    if payment is None or not payment.qualifies:
        return "invalid", None
    uid = tg_user["id"]
    with transaction.atomic():
        enrollment = Enrollment.objects.select_for_update().get(payment=payment)
        if enrollment.telegram_user_id not in (None, uid):
            return "claimed_by_other", enrollment
        if enrollment.telegram_user_id is None and Enrollment.objects.filter(telegram_user_id=uid).exists():
            return "telegram_has_other", enrollment
        if enrollment.status == REVOKED:
            return "revoked", enrollment
        if enrollment.status == EXPIRED:
            return "expired", enrollment
        if enrollment.telegram_user_id is None:
            now = timezone.now()
            enrollment.telegram_user_id = uid
            enrollment.access_start = now
            enrollment.access_expires_at = add_months(now, settings.COURSE["access_months"])
            enrollment.status = ACTIVE
            audit("telegram_linked", reference, f"tg={uid}")
        enrollment.telegram_username = (tg_user.get("username") or "")[:64]
        enrollment.telegram_name = " ".join(
            p for p in (tg_user.get("first_name"), tg_user.get("last_name")) if p
        )[:200]
        enrollment.save()
    return "ok", enrollment


def issue_links(enrollment, fresh=False):
    """Return {space: url}, with None where the person is already a member.
    Unused, unexpired links are reused, so repeated taps never pile up active links.
    fresh=True replaces them, and is capped per day."""
    now = timezone.now()
    if fresh and enrollment.invite_links.filter(created_at__gte=now - timedelta(days=1)).count() >= MAX_LINKS_PER_DAY:
        raise LinkLimitReached()
    out = {}
    for space in JOIN_SPACES:
        chat = chat_for(space)
        if enrollment.telegram_user_id and telegram.is_member(chat, enrollment.telegram_user_id):
            out[space] = None
            continue
        current = enrollment.invite_links.filter(space=space, is_active=True, expires_at__gt=now).first()
        if current and not fresh:
            out[space] = current.url
            continue
        if current:
            _retire(current)
        expires = now + timedelta(hours=settings.COURSE["invite_ttl_hours"])
        data = telegram.create_invite_link(
            chat, int(expires.timestamp()), name=f"sga-{space}-{enrollment.pk}"
        )
        InviteLink.objects.create(enrollment=enrollment, space=space, url=data["invite_link"], expires_at=expires)
        out[space] = data["invite_link"]
    return out


def _retire(link):
    # Only links for a group the bot manages are revoked. Any others expire on their own after 24 hours.
    if link.space in SPACES:
        try:
            telegram.revoke_invite_link(chat_for(link.space), link.url)
        except TelegramError:
            log.warning("could not revoke invite link %s", link.pk)
    link.is_active = False
    link.save(update_fields=["is_active"])


def remove_from_spaces(enrollment):
    if enrollment.telegram_user_id:
        for space in SPACES:
            try:
                telegram.remove_member(chat_for(space), enrollment.telegram_user_id)
            except TelegramError:
                log.warning("could not remove enrollment %s from %s", enrollment.pk, space)
    for link in enrollment.invite_links.filter(is_active=True):
        _retire(link)


def _end(enrollment, status, note, reference):
    enrollment.status = status
    enrollment.admin_note = note[:200]
    enrollment.save(update_fields=["status", "admin_note", "updated_at"])
    remove_from_spaces(enrollment)
    audit(f"access_{status}", reference, note)


def expire_due(now=None):
    """Remove everyone whose 12 months have ended. Run hourly from a Railway cron service."""
    now = now or timezone.now()
    count = 0
    for enrollment in Enrollment.objects.filter(status=ACTIVE, access_expires_at__lte=now):
        _end(enrollment, EXPIRED, "12 months elapsed", enrollment.payment_id)
        count += 1
    return count


def admin_revoke(enrollment, actor):
    if enrollment.status != REVOKED:
        _end(enrollment, REVOKED, f"revoked by {actor}", enrollment.payment_id)


def admin_restore(enrollment, actor):
    """Restore access after a manual revoke. Re-checks Paystack first, so a reversed payment cannot come back."""
    if enrollment.telegram_user_id is None:
        raise ValueError("Student has not connected Telegram yet")
    payment = sync_payment(enrollment.payment_id)  # may raise PaystackError; the caller reports it
    if payment is None or not payment.qualifies:
        raise ValueError("Payment is not valid, so access cannot be restored")
    if enrollment.access_expires_at is None or enrollment.access_expires_at <= timezone.now():
        raise ValueError("The 12 months have already ended")
    enrollment.status = ACTIVE
    enrollment.admin_note = f"restored by {actor}"[:200]
    enrollment.save(update_fields=["status", "admin_note", "updated_at"])
    audit("access_restored", enrollment.payment_id, actor)
    return enrollment
