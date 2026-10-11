from django.conf import settings
from django.core.management.base import BaseCommand

from academy.services import telegram


class Command(BaseCommand):
    help = "Point the bot's webhook at this site. Needs TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and RAILWAY_PUBLIC_DOMAIN."

    def handle(self, *args, **options):
        if not settings.RAILWAY_DOMAIN or not settings.TELEGRAM_WEBHOOK_SECRET:
            self.stderr.write("RAILWAY_PUBLIC_DOMAIN or TELEGRAM_WEBHOOK_SECRET is missing; webhook not set.")
            return
        url = f"https://{settings.RAILWAY_DOMAIN}/telegram/webhook/"
        telegram.set_webhook(url, settings.TELEGRAM_WEBHOOK_SECRET)
        self.stdout.write(f"Telegram webhook set to {url}")
