# Sales Growth Academy: Montessori & Learning Resources Masterclass

Django backend and landing page. A student pays on Paystack, the payment is verified with Paystack, their Telegram account is tied to that payment, and they get 12 months of access to the classroom. Nobody confirms anything by hand.

## What is in the box

| Path | What it does |
|---|---|
| `academy/views.py` | Landing page, success page, Paystack webhook, Telegram webhook, staff dashboard |
| `academy/services/paystack.py` | Verifies transactions with Paystack and checks the webhook signature |
| `academy/services/access.py` | The rules: amount and currency checks, Telegram identity, idempotency, 12-month expiry, revoke and restore |
| `academy/services/delivery.py` | Sends each student their own one-use join links |
| `academy/bot.py` | Telegram bot: `/start <reference>`, Check Payment Again, Get New Links |
| `academy/admin.py` | Admin: search by email, reference or Telegram ID; revoke and restore actions |
| `academy/management/commands/` | `expire_access` (hourly), `setup_telegram`, `ensure_admin` |
| `academy/tests/` | Tests for payment rules, idempotency, expiry, signatures and duplicate Telegram updates |
| `railway.json`, `start.sh` | Railway configuration |

## Before you start: two things only you can do

1. **Paystack test mode.** Use `sk_test_...` for `PAYSTACK_SECRET_KEY` until the end-to-end test passes. Switch to `sk_live_...` only after that.
2. **Images.** The logo, banner and second image did not reach the build. Place these files (PNG) in `academy/static/academy/img/`, then commit them:
   - `logo.png`: header logo, no text
   - `banner.png`: hero banner (the name Abraham Precious is written on the page, not in the image)
   - `surroundings.png`: the second image section
   Until they are added, the page still works. The logo area is empty and the banner shows a blue panel.

## Run it on your computer (Git Bash)

Open **Git Bash** in the project folder, then:

```bash
python -m venv .venv
source .venv/Scripts/activate          # Windows; on Mac/Linux use: source .venv/bin/activate
pip install -r requirements.txt

# Create the database migration once, then commit the file it creates
python manage.py makemigrations academy
git add academy/migrations/ && git commit -m "Add initial migration"

# Run the tests (they use mocks, so no Paystack or Telegram calls are made)
python manage.py test academy -v 2

# Run the site
export DJANGO_DEBUG=1
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000 for the landing page and http://127.0.0.1:8000/admin/ for the admin.

The migration step matters: the project is delivered without a generated migration file, because it had to be created on a machine with Django installed. Run `makemigrations` once and commit `academy/migrations/0001_initial.py` before you deploy.

## Put it on Railway

1. **Push to GitHub** (or deploy with the Railway CLI). In Git Bash:
   ```bash
   git init && git add -A && git commit -m "Initial academy backend"
   git branch -M main
   git remote add origin https://github.com/kunlesxo/sales-growth.git
   git push -u origin main
   ```
2. In Railway, **New Project > Deploy from GitHub repo**, and pick the repo.
3. **Add Postgres:** New > Database > PostgreSQL. Railway creates the `DATABASE_URL` variable for it.
4. **Web service > Variables:** add every name from `.env.example` that is not commented out. Use the **test** Paystack key and the bot token. Do not paste secrets into chat.
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
   - `DJANGO_SECRET_KEY` = a long random string
5. **Web service > Settings > Networking:** generate a public domain. Railway sets `RAILWAY_PUBLIC_DOMAIN` automatically, so redeploy after adding the domain.
6. **Deploy.** `start.sh` runs the migrations, creates the admin login, and points the Telegram bot at `https://<your-domain>/telegram/webhook/`. Check the deploy logs for `Telegram webhook set to ...`.
7. **Paystack dashboard > Settings > Webhooks:** set the URL to `https://<your-domain>/paystack/webhook/`. Paystack sends `charge.success` events there.
8. **Expiry service (cron):** in the Railway project, add a second service from the same repo. Set its start command to `python manage.py expire_access` and its cron schedule to `0 * * * *` (hourly). It removes students whose 12 months have ended.

## Environment variables

| Name | Needed | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | yes | Long random string |
| `DATABASE_URL` | yes on Railway | Reference the Postgres service |
| `PAYSTACK_SECRET_KEY` | yes | `sk_test_...` first, then `sk_live_...` |
| `TELEGRAM_BOT_TOKEN` | yes | Token of the existing bot |
| `TELEGRAM_WEBHOOK_SECRET` | yes | Random string; Telegram must send it back |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` | yes | Admin login, reset on each deploy |
| `PRICE_GHS_PESEWAS` | for Ghana | Empty keeps GHS off |
| `SUPPORT_WHATSAPP_URL` | recommended | Fallback button only |
| `RAILWAY_PUBLIC_DOMAIN` | automatic | Set by Railway |

The Telegram chat IDs and the bot username are fixed in `config/settings.py`. They are not secrets.

## How a purchase flows

1. The student pays on https://paystack.shop/pay/-skbprjgs2.
2. Paystack redirects to `/success/?reference=...`. The page asks Paystack to verify the reference. It shows **PAYMENT SUCCESSFUL** only when Paystack confirms it.
3. **GET MY TELEGRAM ACCESS** opens `t.me/Salesgrowthacademyaccessbot?start=<reference>`.
4. The bot checks the reference with Paystack again, then ties the payment to that Telegram account. The first connection starts the 12 months.
5. The bot sends one-use join links, one per space. Each link expires after 24 hours and admits one person.
6. Pressing the link again changes nothing. Old links are reused until they are used. **Get New Links** replaces them (max 10 a day).
7. If the student closes the browser, they can enter their reference on the landing page or open `/success/?reference=...` later.

### Rules that protect the money and the group

- Success needs `status = success`, currency `NGN` (or `GHS` once priced), an amount from the price up to 5% above it (Paystack's fee is passed to the customer), and a reference that matches.
- The Paystack reference is the key: a payment is stored once, and one payment gives one enrollment.
- One enrollment is tied to one Telegram account, and one Telegram account is tied to one purchase.
- Webhook signatures are checked with HMAC-SHA512 before anything is read. Telegram webhooks must include the secret token, and each update is handled once.
- A reversed payment revokes access at the next check, and the student is removed from the classroom.

## Admin

- `/admin/`: students, payments and the audit log. Search students by email, name, Paystack reference, Telegram ID or username.
- Select students, then the actions **Revoke access now** or **Restore access and send fresh join links**. Restore checks Paystack again first.
- `/dashboard/` (staff login): totals for paid students, Telegram-connected, not connected, active, expired and revoked, plus the latest 25 students.

## Ghana

- Paystack processes Ghanaian cards and mobile money. Its Ghana page confirms card and mobile money; it does not state the GHS settlement terms, so confirm with Paystack that the payment page will charge GHS before you go live.
- The site shows a GHS option only when `PRICE_GHS_PESEWAS` is set. Set it to the cedi price you have agreed.

## Scale

Students are rows in Postgres with indexes on status, expiry and Telegram ID, and the expiry job reads only the rows that are due. The design is sized for 500 to 1,000 students, but that has not been load-tested. Keep the web service at one replica so that migrations run once. Check the Railway replica setting after deploying.

## Known limits

- The second-image section and the banner use the image files you add. Their content is not generated.
- Telegram removes a student with a ban followed by an unban. This works for channels and groups where the bot is an admin, and the student can rejoin with a new link.
- Telegram does not report when a join link is used, so "Get New Links" is the way to recover a link that stopped working.
