"""Database structure. The Paystack reference is the idempotency key for every purchase."""
from django.db import models


class Payment(models.Model):
    """One Paystack transaction, keyed by its reference (so the same payment can never be stored twice)."""

    reference = models.CharField(max_length=100, primary_key=True)
    paystack_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=30, blank=True)
    amount = models.BigIntegerField(null=True, blank=True, help_text="Minor units: kobo or pesewas")
    currency = models.CharField(max_length=8, blank=True)
    email = models.CharField(max_length=254, blank=True, db_index=True)
    customer_name = models.CharField(max_length=200, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True, db_index=True)
    qualifies = models.BooleanField(default=False, db_index=True)
    reject_reason = models.CharField(max_length=80, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference


class Enrollment(models.Model):
    """A verified purchase, connected (or not yet) to one Telegram account, with a 12-month window."""

    class Status(models.TextChoices):
        UNLINKED = "unlinked", "Paid, Telegram not connected"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        REVOKED = "revoked", "Revoked"

    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="enrollment")
    email = models.CharField(max_length=254, blank=True, db_index=True)
    customer_name = models.CharField(max_length=200, blank=True)
    telegram_user_id = models.BigIntegerField(null=True, blank=True, unique=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    telegram_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UNLINKED, db_index=True)
    purchased_at = models.DateTimeField()
    access_start = models.DateTimeField(null=True, blank=True)
    access_expires_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-purchased_at"]
        indexes = [models.Index(fields=["status", "access_expires_at"], name="enr_status_expiry_idx")]

    def __str__(self):
        return self.email or self.payment_id


class InviteLink(models.Model):
    """A one-person Telegram join link. Only unused, unexpired links are reused."""

    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="invite_links")
    space = models.CharField(max_length=12, choices=[("classroom", "Classroom"), ("discussion", "Discussion & Q&A")])
    url = models.CharField(max_length=300, unique=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["enrollment", "space", "is_active"], name="invite_lookup_idx")]


class TelegramUpdate(models.Model):
    """Telegram update ids already handled. Telegram retries, so this stops a repeat from running twice."""

    update_id = models.BigIntegerField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=60)
    reference = models.CharField(max_length=100, blank=True, db_index=True)
    detail = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.reference}"
