"""Settings. Every secret comes from an environment variable (Railway > Variables). Nothing secret lives in code."""
import os
import sys
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=""):
    return os.environ.get(name, default).strip()


DEBUG = env("DJANGO_DEBUG") == "1"
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or any(cmd in sys.argv for cmd in ("collectstatic", "test")):
        SECRET_KEY = "dev-only-insecure-key"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY is not set. Add it in Railway > Variables.")

RAILWAY_DOMAIN = env("RAILWAY_PUBLIC_DOMAIN")
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "healthcheck.railway.app", ".up.railway.app","salesgrowthacademy.org",   "sales-growth-vlag-ewjdrzibz-cirus-projects.vercel.app","salesgrowthacademy.com" ]
if RAILWAY_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_DOMAIN)
ALLOWED_HOSTS += [h for h in env("EXTRA_ALLOWED_HOSTS").split(",") if h]
CSRF_TRUSTED_ORIGINS = [f"https://{RAILWAY_DOMAIN}"] if RAILWAY_DOMAIN else []
# Your own domain for logins, with the scheme, e.g. https://example.com,https://www.example.com
CSRF_TRUSTED_ORIGINS += [o for o in env("EXTRA_CSRF_TRUSTED_ORIGINS").split(",") if o]

INSTALLED_APPS = [
    # academy comes first so its templates/admin/login.html overrides Django's admin login page
    "academy.apps.AcademyConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Local SQLite for development; Railway sets DATABASE_URL to its Postgres.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^health/?$"]  # Railway health checks arrive over plain HTTP
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600

# ----- Business settings -------------------------------------------------------
# Prices are in minor units: NGN kobo (35,000 naira = 3,500,000) and GHS pesewas.
# GHS stays off (0) until you set PRICE_GHS_PESEWAS and confirm GHS is enabled on the Paystack page.
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY")
# Railway variables switch between test and live without a code change:
#   PAYSTACK_SECRET_KEY (sk_test_… or sk_live_…), PAYSTACK_PAGE_URL (the matching payment page), PRICE_NGN_KOBO.
PAYSTACK_PAGE_URL = env("PAYSTACK_PAGE_URL") or "https://paystack.shop/pay/-skbprjgs2"

COURSE = {
    "brand": "Sales Growth Academy",
    "name": "Montessori & Learning Resources Masterclass",
    "instructor": "Abraham Precious",
    "start_label": "28 December 2026, 8:00 PM WAT",
    "start_iso": "2026-12-28T20:00:00+01:00",   # drives the countdown on the landing page
    # Launch price ₦35,000. Railway variable PRICE_NGN_KOBO overrides it, e.g. 100000 for a ₦1,000 test.
    # Keep this equal to the amount on the Paystack payment page, or payments are rejected.
    "price_ngn_kobo": int(env("PRICE_NGN_KOBO") or 3_500_000),
    "price_ghs_pesewas": int(env("PRICE_GHS_PESEWAS") or 0),
    "tolerance_pct": 5,          # Paystack fee is passed to the customer: accept up to 5% above price
    "access_months": 12,
    "invite_ttl_hours": 24,      # unused join links expire after this
}

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = "Salesgrowthacademyaccessbot"
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET")
CLASSROOM_CHAT_ID = int(env("CLASSROOM_CHAT_ID") or -1004498169669)
DISCUSSION_CHAT_ID = int(env("DISCUSSION_CHAT_ID") or -1004365675295)

SUPPORT_WHATSAPP_URL = env("SUPPORT_WHATSAPP_URL")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
