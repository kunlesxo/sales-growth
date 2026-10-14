from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("success/", views.success, name="success"),
    path("refund-policy/", views.refund_policy, name="refund_policy"),
    path("health/", views.health, name="health"),
    path("paystack/webhook/", views.paystack_webhook, name="paystack_webhook"),
    path("telegram/webhook/", views.telegram_webhook, name="telegram_webhook"),
    path("dashboard/", views.dashboard, name="dashboard"),
]
