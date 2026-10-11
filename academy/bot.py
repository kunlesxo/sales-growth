"""Telegram bot logic. The only way in is /start <payment reference>, and every reference is re-checked with Paystack."""
import logging
import re

from .models import Enrollment
from .services import access, delivery, telegram
from .services.paystack import PaystackError
from .services.telegram import TelegramError

log = logging.getLogger(__name__)

REF_RE = re.compile(r"^[A-Za-z0-9_-]{4,50}$")  # also the Telegram deep-link rule: letters, digits, _ and -

VERIFIED = "🎉 PAYMENT VERIFIED!\n\nWelcome to the Sales Growth Academy Montessori & Learning Resources Masterclass."
BUSY = "We're checking your payment with our payment provider. Please tap Check Payment Again in a moment."
INVALID = (
    "We couldn't verify your course payment yet.\n\n"
    "If you have just completed payment, please wait a moment and tap Check Payment Again.\n\n"
    "If the problem continues, contact Sales Growth Academy support."
)
REASONS = {
    "claimed_by_other": "This payment is already connected to another Telegram account. Contact support if this is a mistake.",
    "telegram_has_other": "Your Telegram account is already connected to a different purchase. Contact support if you need help.",
    "revoked": "Access for this purchase is not active. Contact support if you think this is a mistake.",
    "expired": "The 12 months of access for this purchase have ended.",
}


def handle_update(update):
    if "message" in update:
        _on_message(update["message"])
    elif "callback_query" in update:
        _on_callback(update["callback_query"])


def _reply(chat_id, text, buttons=None):
    try:
        telegram.send_message(chat_id, text, buttons)
    except TelegramError:
        log.exception("sendMessage failed")


def _on_message(msg):
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or "from" not in msg:
        return
    user, chat_id = msg["from"], chat["id"]
    text = (msg.get("text") or "").strip()
    if not text.startswith("/start"):
        return _reply(chat_id, "Open your payment success page and tap GET MY TELEGRAM ACCESS to connect your purchase.")
    arg = text[len("/start"):].strip()
    if not arg:
        return _returning(chat_id, user)
    if not REF_RE.match(arg):
        return _invalid(chat_id, None)
    return _claim(chat_id, user, arg)


def _returning(chat_id, user):
    """/start with no reference from someone already connected: resend their links."""
    enrollment = Enrollment.objects.filter(telegram_user_id=user["id"], status=Enrollment.Status.ACTIVE).first()
    if enrollment:
        return delivery.deliver(chat_id, enrollment, "Welcome back! Here are your links.")
    _reply(chat_id, "Open the link from your payment success page to connect your purchase.")


def _claim(chat_id, user, reference):
    try:
        outcome, enrollment = access.claim(reference, user)
    except PaystackError:
        log.warning("Paystack unreachable while checking a Telegram start")
        return _reply(chat_id, BUSY, [[delivery.check_again_button(reference)]])
    if outcome == "ok":
        return delivery.deliver(chat_id, enrollment, VERIFIED)
    if outcome == "invalid":
        return _invalid(chat_id, reference)
    _reply(chat_id, REASONS.get(outcome, INVALID), delivery.support_row() or None)


def _invalid(chat_id, reference):
    buttons = [[delivery.check_again_button(reference)]] if reference else []
    buttons += delivery.support_row()
    _reply(chat_id, INVALID, buttons or None)


def _on_callback(cb):
    try:
        telegram.answer_callback(cb["id"])  # stop the button spinner first
    except TelegramError:
        pass
    chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
    if chat_id is None:
        return
    user = cb["from"]
    kind, _, reference = (cb.get("data") or "").partition(":")
    if not REF_RE.match(reference):
        return
    if kind == "check":
        return _claim(chat_id, user, reference)
    if kind == "fresh":
        enrollment = Enrollment.objects.filter(
            payment_id=reference, telegram_user_id=user["id"], status=Enrollment.Status.ACTIVE
        ).first()
        if enrollment is None:
            return _reply(chat_id, "Your access is not active, so new links cannot be issued.")
        return delivery.deliver(chat_id, enrollment, "Here are your new links. The old ones stop working.", fresh=True)
