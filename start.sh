#!/bin/sh
# Railway start command for the WEB service.
# 1) create the database tables, 2) create or update the admin login from env vars,
# 3) point the Telegram bot at this site, 4) serve the site.
set -e
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py ensure_admin || echo "admin setup skipped"
python manage.py setup_telegram || echo "telegram webhook not set (check the variables)"
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-3}" --timeout 60 --access-logfile -
