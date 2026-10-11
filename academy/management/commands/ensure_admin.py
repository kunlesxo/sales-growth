import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update the admin login from ADMIN_USERNAME, ADMIN_EMAIL and ADMIN_PASSWORD (Railway variables)."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "").strip()
        email = os.environ.get("ADMIN_EMAIL", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")
        if not (username and password):
            self.stdout.write("ADMIN_USERNAME or ADMIN_PASSWORD not set; skipping admin setup.")
            return
        User = get_user_model()
        user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
        user.email = email or user.email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(f"Admin login ready for {username}.")
