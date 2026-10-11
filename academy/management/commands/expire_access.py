from django.core.management.base import BaseCommand

from academy.services import access


class Command(BaseCommand):
    help = "Remove students whose 12-month access has ended. Schedule this hourly (Railway cron service)."

    def handle(self, *args, **options):
        count = access.expire_due()
        self.stdout.write(f"Expired {count} enrollment(s).")
