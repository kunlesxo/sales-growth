"""Sends the join links to a student. Used by the bot and by admin restores."""
import logging

from django.conf import settings

from . import access, telegram
from .telegram import TelegramError

log = logging.getLogger(__name__)

SPACE_LABELS = {
    "classroom": ("Classroom", "JOIN CLASSROOM"),
}


def check_again_button(reference):
    return {"text": "Check Payment Again", "callback_data": f"check:{reference}"}


def support_row():
    url = settings.SUPPORT_WHATSAPP_URL
    return [[{"text": "CONTACT SUPPORT", "url": url}]] if url.startswith("https://") else []


def deliver(chat_id, enrollment, intro, fresh=False):
    """Send the join links for the waiting classroom. Each person gets their own one-use links."""
    reference = enrollment.payment_id
    try:
        links = access.issue_links(enrollment, fresh=fresh)
    except access.LinkLimitReached:
        return telegram.send_message(
            chat_id,
            "You have asked for too many new links today. Please try again tomorrow, or contact support.",
            support_row() or None,
        )
    except TelegramError:
        log.exception("could not create links for enrollment %s", enrollment.pk)
        return telegram.send_message(
            chat_id,
            "We could not create your links just now. Please tap Check Payment Again in a moment.",
            [[check_again_button(reference)]],
        )

    lines = [intro, ""]
    buttons = []
    for space in access.SPACES:
        label, button = SPACE_LABELS[space]
        url = links.get(space)
        if url:
            buttons.append([{"text": button, "url": url}])
        else:
            lines.append(f"You're already in the {label.lower()}.")
    lines += [
        "",
        f"Your access is valid for {settings.COURSE['access_months']} months, until "
        f"{enrollment.access_expires_at:%d %B %Y}.",
    ]
    return telegram.send_message(chat_id, "\n".join(lines), buttons)
