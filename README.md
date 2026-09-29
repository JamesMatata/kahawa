# Kahawa

Cafe storefront and staff tools for a Nairobi coffee shop. Customers browse the menu, build a bag, and pay with M-Pesa or order from a table QR. Staff run the floor from `/manage`: live orders, sales, catalog, packages, tables, gift cards, and team.

## Requirements

- Python 3.10+
- Node.js (only to build the CSS)

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py seed_kahawa
npm install
npm run build:css
python manage.py runserver
```

On macOS or Linux, activate the virtual environment with `source .venv/bin/activate` and copy the env file with `cp .env.example .env`.

The store is at [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Manage is at [http://127.0.0.1:8000/manage/](http://127.0.0.1:8000/manage/).

After seeding, sign in to Manage with:

| Role | Username | Password |
| --- | --- | --- |
| Admin | `staff` | `kahawa2026!` |
| Barista | `barista` | `barista2026!` |

`seed_kahawa` is safe to run again. It refreshes the demo catalog, tables, and those two logins.

## Configuration

Settings come from `.env`. Start from `.env.example` and do not commit `.env`.

- `DEBUG` and `SECRET_KEY` — local defaults are for development only.
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` — include your ngrok address if you open the site through a tunnel. `https://*.ngrok-free.app` is already listed so a new free tunnel can still submit login forms.
- `SMS_PROVIDER=console` prints texts in the terminal. Set `africastalking` and the `AT_*` keys to send real SMS.
- `MPESA_MODE=mock` simulates STK push. `live` uses Daraja with the `MPESA_*` keys. Leave `MPESA_CALLBACK_SECRET` empty while mocking.
- `ETIMS_*` holds the KRA OSCU PIN, branch id, device serial, and communication key. Leave them blank until the device is initialised. Receipts stay unmarked.

While you change Tailwind classes, run `npm run watch:css`. Commit the built file `static/css/kahawa.css`; the pages do not load Tailwind from a CDN.

## What is in the box

- Menu, bag, pickup, delivery, and dine-in from a table QR (`/t/<code>/`).
- M-Pesa checkout, receipts, and a kitchen ticket.
- Manage: live ops, sales PDF, products, packages, categories, tables, gift cards, and team roles.
