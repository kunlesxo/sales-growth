"""Paystack server-side calls. The secret key lives only in the PAYSTACK_SECRET_KEY environment variable."""
import hashlib
import hmac
from urllib.parse import quote

import requests
from django.conf import settings

API = "https://api.paystack.co"


class PaystackError(Exception):
    """Paystack was unreachable or returned a server error. Safe to retry later."""


def valid_signature(raw_body, signature):
    """Check the x-paystack-signature header: HMAC-SHA512 of the raw request body, keyed with the secret key."""
    key = settings.PAYSTACK_SECRET_KEY
    if not key or not signature:
        return False
    expected = hmac.new(key.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_transaction(reference):
    """GET /transaction/verify/:reference. Returns the transaction dict, or None if Paystack does not know it."""
    if not settings.PAYSTACK_SECRET_KEY:
        raise PaystackError("PAYSTACK_SECRET_KEY is not set")
    try:
        r = requests.get(
            f"{API}/transaction/verify/{quote(reference, safe='')}",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise PaystackError("Paystack unreachable") from exc
    if r.status_code >= 500:
        raise PaystackError(f"Paystack returned {r.status_code}")
    try:
        body = r.json()
    except ValueError as exc:
        raise PaystackError("Paystack returned a non-JSON response") from exc
    if r.status_code != 200 or not body.get("status"):
        return None
    return body.get("data")
