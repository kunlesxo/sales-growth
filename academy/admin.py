from django.contrib import admin, messages
from django.db.models import Q

from .models import AuditLog, Enrollment, InviteLink, Payment
from .services import access, delivery
from .services.paystack import PaystackError

admin.site.site_header = "Sales Growth Academy · Admin"
admin.site.site_title = "SGA Admin"
admin.site.index_title = "Students & payments"


@admin.action(description="Revoke access now (removes from the classroom)")
def revoke_access(modeladmin, request, queryset):
    count = 0
    for enrollment in queryset:
        access.admin_revoke(enrollment, actor=request.user.get_username())
        count += 1
    messages.success(request, f"Revoked {count} student(s).")


@admin.action(description="Restore access and send fresh join links")
def restore_access(modeladmin, request, queryset):
    for enrollment in queryset:
        try:
            access.admin_restore(enrollment, actor=request.user.get_username())
            delivery.deliver(
                enrollment.telegram_user_id,
                enrollment,
                "Your access has been restored. Here are your new links.",
                fresh=True,
            )
        except (ValueError, PaystackError) as exc:
            messages.warning(request, f"{enrollment.email or enrollment.payment_id}: {exc}")
        except Exception as exc:  # report, never crash the whole batch
            messages.warning(request, f"{enrollment.email or enrollment.payment_id}: could not send links ({exc})")


class InviteLinkInline(admin.TabularInline):
    model = InviteLink
    extra = 0
    can_delete = False
    readonly_fields = ("space", "url", "expires_at", "is_active", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("email", "customer_name", "payment", "telegram_user_id", "telegram_username",
                    "status", "purchased_at", "access_expires_at")
    list_filter = ("status", "purchased_at")
    search_fields = ("email", "customer_name", "telegram_username")
    readonly_fields = ("payment", "email", "customer_name", "telegram_user_id", "telegram_username",
                       "telegram_name", "status", "purchased_at", "access_start", "access_expires_at",
                       "admin_note", "updated_at")
    actions = [revoke_access, restore_access]
    inlines = [InviteLinkInline]
    list_per_page = 50
    date_hierarchy = "purchased_at"

    def get_search_results(self, request, queryset, search_term):
        """Search by email, name, Paystack reference, Telegram ID or Telegram username."""
        q = (search_term or "").strip()
        if not q:
            return queryset, False
        cond = (
            Q(email__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(telegram_username__icontains=q)
            | Q(payment__reference__iexact=q)
        )
        if q.isdigit():
            cond |= Q(telegram_user_id=int(q))
        return queryset.filter(cond).distinct(), False

    def has_add_permission(self, request):
        return False  # students are created by payments, never by hand


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "email", "amount", "currency", "status", "qualifies", "reject_reason", "paid_at")
    list_filter = ("status", "qualifies", "currency")
    search_fields = ("reference", "email", "customer_name")
    list_per_page = 50

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # view only: payments come from Paystack


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "reference", "detail")
    search_fields = ("reference", "action", "detail")
    readonly_fields = ("created_at", "action", "reference", "detail")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
