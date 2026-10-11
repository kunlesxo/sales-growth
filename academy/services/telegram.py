"""Telegram Bot API calls (https://core.telegram.org/bots/api). Needs only TELEGRAM_BOT_TOKEN from the environment."""
import requests
from django.conf import settings


class TelegramError(Exception):
    pass


def call(method, **params):
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=15)
        data = r.json()
    except (requests.RequestException, ValueError):
        # Deliberately no exception text: it can contain the request URL, and the URL contains the token.
        raise TelegramError(f"{method}: network or parse error") from None
    if not data.get("ok"):
        raise TelegramError(f"{method}: {data.get('description', 'unknown error')}")
    return data["result"]


def send_message(chat_id, text, buttons=None):
    """buttons is a list of rows. Each button is {"text": ..., "url": ...} or {"text": ..., "callback_data": ...}."""
    params = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    return call("sendMessage", **params)


def answer_callback(callback_id, text=""):
    return call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])


def create_invite_link(chat_id, expire_unix, name):
    """A controlled link: one use only (member_limit=1) and it expires. Never a permanent link."""
    return call(
        "createChatInviteLink",
        chat_id=chat_id,
        expire_date=expire_unix,
        member_limit=1,
        name=name[:32],
    )


def revoke_invite_link(chat_id, url):
    return call("revokeChatInviteLink", chat_id=chat_id, invite_link=url)


def is_member(chat_id, user_id):
    try:
        member = call("getChatMember", chat_id=chat_id, user_id=user_id)
    except TelegramError:
        return False
    return member.get("status") in ("creator", "administrator", "member")


def remove_member(chat_id, user_id):
    """Remove without a permanent ban: ban, then unban, so the person can rejoin later with a new link."""
    call("banChatMember", chat_id=chat_id, user_id=user_id)
    call("unbanChatMember", chat_id=chat_id, user_id=user_id, only_if_banned=True)


def set_webhook(url, secret):
    return call(
        "setWebhook",
        url=url,
        secret_token=secret,
        allowed_updates=["message", "callback_query"],
    )
