"""Tests for the payment rules, Telegram identity matching, idempotency, expiry and webhooks.
Paystack and Telegram are mocked, so these tests never touch the network."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone as dt_tz
from itertools import count
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from academy.models import Enrollment, Payment
from academy.services import access

PRICE = settings.COURSE["price_ngn_kobo"]  # follows the configured price, so these tests hold at any price
USER = {"id": 555, "username": "ada", "first_name": "Ada"}
OTHER = {"id": 777, "username": "bola", "first_name": "Bola"}
NO_SSL = override_settings(SECURE_SSL_REDIRECT=False)


def tx(reference="SGA-TEST-0001", status="success", currency="NGN", amount=PRICE):
    return {
        "id": 4242,
        "reference": reference,
        "status": status,
        "currency": currency,
        "amount": amount,
        "paid_at": "2026-12-01T10:00:00.000Z",
        "customer": {"email": "ada@example.com", "first_name": "Ada", "last_name": "Lovelace"},
    }


class JudgeTests(SimpleTestCase):
    @override_settings(COURSE={**settings.COURSE, "price_ghs_pesewas": 0})
    def test_exact_price_qualifies(self):
        self.assertEqual(access.judge(tx()), (True, ""))

    @override_settings(COURSE={**settings.COURSE, "price_ghs_pesewas": 0})
    def test_fee_margin_qualifies(self):
        # Paystack adds its fee on top, so a slightly higher amount is still the right purchase.
        self.assertEqual(access.judge(tx(amount=PRICE * 103 // 100)), (True, ""))

    @override_settings(COURSE={**settings.COURSE, "price_ghs_pesewas": 0})
    def test_too_high_is_rejected(self):
        self.assertEqual(access.judge(tx(amount=PRICE * 110 // 100))[1], "amount_too_high")

    @override_settings(COURSE={**settings.COURSE, "price_ghs_pesewas": 0})
    def test_too_low_is_rejected(self):
        self.assertEqual(access.judge(tx(amount=PRICE - 1))[1], "amount_too_low")

    @override_settings(COURSE={**settings.COURSE, "price_ghs_pesewas": 0})
    def test_failed_status_is_rejected(self):
        self.assertFalse(access.judge(tx(status="failed"))[0])

    @override_settings(COURSE={**settings.COURSE, "price_ghs_pesewas": 0})
    def test_unknown_currency_is_rejected(self):
        self.assertEqual(access.judge(tx(currency="USD"))[1], "currency_not_accepted")

    @override_settings(COURSE={**settings.COURSE, "price_ghs_pesewas": 0})
    def test_ghs_rejected_until_a_price_is_set(self):
        self.assertEqual(access.judge(tx(currency="GHS", amount=100_000))[1], "currency_not_accepted")

    @override_settings(COURSE={**settings.COURSE, "price_ghs_pesewas": 50_000})
    def test_ghs_accepted_once_priced(self):
        self.assertEqual(access.judge(tx(currency="GHS", amount=50_000)), (True, ""))

    def test_add_months_clamps_to_month_end(self):
        start = datetime(2026, 1, 31, tzinfo=dt_tz.utc)
        self.assertEqual(access.add_months(start, 1).day, 28)
        self.assertEqual(access.add_months(start, 12).year, 2027)


@NO_SSL
class ClaimTests(TestCase):
    def paystack(self, **kwargs):
        patcher = patch("academy.services.paystack.verify_transaction", **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def telegram(self, name, **kwargs):
        patcher = patch(f"academy.services.telegram.{name}", **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def test_repeat_claims_are_idempotent_and_12_months_starts_once(self):
        self.paystack(return_value=tx())
        first, _ = access.claim("SGA-TEST-0001", USER)
        second, _ = access.claim("SGA-TEST-0001", USER)
        self.assertEqual((first, second), ("ok", "ok"))
        self.assertEqual(Enrollment.objects.count(), 1)
        enrollment = Enrollment.objects.get()
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)
        self.assertGreaterEqual((enrollment.access_expires_at - enrollment.access_start).days, 360)
        self.assertLessEqual((enrollment.access_expires_at - enrollment.access_start).days, 370)
        self.assertEqual(Payment.objects.count(), 1)

    def test_second_telegram_account_cannot_take_the_purchase(self):
        self.paystack(return_value=tx())
        access.claim("SGA-TEST-0001", USER)
        outcome, _ = access.claim("SGA-TEST-0001", OTHER)
        self.assertEqual(outcome, "claimed_by_other")

    def test_one_telegram_account_cannot_claim_two_purchases(self):
        self.paystack(side_effect=lambda ref: tx(reference=ref))
        access.claim("SGA-TEST-0001", USER)
        outcome, _ = access.claim("SGA-TEST-0002", USER)
        self.assertEqual(outcome, "telegram_has_other")

    def test_unknown_reference_is_invalid(self):
        self.paystack(return_value=None)
        self.assertEqual(access.claim("SGA-NOPE-0001", USER), ("invalid", None))
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_failed_payment_gets_no_access(self):
        self.paystack(return_value=tx(status="failed"))
        outcome, _ = access.claim("SGA-TEST-0001", USER)
        self.assertEqual(outcome, "invalid")
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_reversed_payment_revokes_existing_access(self):
        self.paystack(return_value=tx())
        access.claim("SGA-TEST-0001", USER)
        remove = self.telegram("remove_member")
        self.paystack(return_value=tx(status="reversed"))  # overrides the patch above for this call
        access.sync_payment("SGA-TEST-0001")
        self.assertEqual(Enrollment.objects.get().status, Enrollment.Status.REVOKED)
        self.assertEqual(remove.call_count, 2)  # removed from classroom and discussion

    def test_expiry_removes_members_and_marks_expired(self):
        self.paystack(return_value=tx())
        access.claim("SGA-TEST-0001", USER)
        Enrollment.objects.update(access_expires_at=timezone.now() - timedelta(minutes=1))
        remove = self.telegram("remove_member")
        self.assertEqual(access.expire_due(), 1)
        self.assertEqual(access.expire_due(), 0)  # second run changes nothing
        self.assertEqual(Enrollment.objects.get().status, Enrollment.Status.EXPIRED)
        self.assertEqual(remove.call_count, 2)

    def test_unused_links_are_reused_and_one_per_space(self):
        self.paystack(return_value=tx())
        _, enrollment = access.claim("SGA-TEST-0001", USER)
        ids = count()
        create = self.telegram(
            "create_invite_link",
            side_effect=lambda chat, exp, name: {"invite_link": f"https://t.me/+link{next(ids)}"},
        )
        self.telegram("is_member", return_value=False)
        first = access.issue_links(enrollment)
        second = access.issue_links(enrollment)
        self.assertEqual(first, second)
        self.assertEqual(create.call_count, 1)  # one per join space, however many times the student taps

    def test_fresh_links_replace_the_old_ones(self):
        self.paystack(return_value=tx())
        _, enrollment = access.claim("SGA-TEST-0001", USER)
        ids = count()
        create = self.telegram(
            "create_invite_link",
            side_effect=lambda chat, exp, name: {"invite_link": f"https://t.me/+link{next(ids)}"},
        )
        revoke = self.telegram("revoke_invite_link")
        self.telegram("is_member", return_value=False)
        access.issue_links(enrollment)
        access.issue_links(enrollment, fresh=True)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(revoke.call_count, 1)
        self.assertEqual(enrollment.invite_links.filter(is_active=True).count(), 1)


@NO_SSL
class WebhookTests(TestCase):
    @override_settings(PAYSTACK_SECRET_KEY="sk_test_unit")
    def test_bad_paystack_signature_is_rejected(self):
        response = self.client.post(
            "/paystack/webhook/",
            data=b'{"event":"charge.success","data":{"reference":"SGA-TEST-0009"}}',
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="not-a-real-signature",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Payment.objects.count(), 0)

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_unit", COURSE={**settings.COURSE, "price_ghs_pesewas": 0})
    def test_valid_signed_charge_success_records_the_payment(self):
        body = json.dumps({"event": "charge.success", "data": {"reference": "SGA-TEST-0009"}}).encode()
        signature = hmac.new(b"sk_test_unit", body, hashlib.sha512).hexdigest()
        with patch("academy.services.paystack.verify_transaction", return_value=tx(reference="SGA-TEST-0009")):
            response = self.client.post(
                "/paystack/webhook/", data=body, content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=signature
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Payment.objects.get(reference="SGA-TEST-0009").qualifies)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="s3cret")
    def test_telegram_update_is_handled_once(self):
        update = {"update_id": 900001, "message": {"text": "/start SGA-TEST-0001"}}
        with patch("academy.bot.handle_update") as handle:
            first = self.client.post(
                "/telegram/webhook/", data=json.dumps(update), content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret",
            )
            second = self.client.post(
                "/telegram/webhook/", data=json.dumps(update), content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret",
            )
        self.assertEqual(handle.call_count, 1)
        self.assertEqual(first.content, b"ok")
        self.assertEqual(second.content, b"duplicate")

    @override_settings(TELEGRAM_WEBHOOK_SECRET="s3cret")
    def test_telegram_wrong_secret_is_rejected(self):
        response = self.client.post(
            "/telegram/webhook/", data=json.dumps({"update_id": 1}), content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="wrong",
        )
        self.assertEqual(response.status_code, 403)


@NO_SSL
class PageTests(TestCase):
    def test_landing_page_has_pay_button_and_no_retired_platform(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, settings.PAYSTACK_PAGE_URL)
        self.assertContains(response, "Abraham Precious")
        self.assertNotContains(response, "16" + "88")  # the retired platform name must never appear

    def test_success_page_without_reference_does_not_grant_anything(self):
        response = self.client.get("/success/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "GET MY TELEGRAM ACCESS")

    def test_success_page_shows_pending_for_unknown_reference(self):
        with patch("academy.services.paystack.verify_transaction", return_value=None):
            response = self.client.get("/success/?reference=SGA-NOPE-0001")
        self.assertContains(response, "reference=SGA-NOPE-0001")  # the retry link keeps the reference
        self.assertNotContains(response, "t.me/")  # no Telegram link until Paystack confirms payment

    def test_health_check(self):
        self.assertEqual(self.client.get("/health/").status_code, 200)