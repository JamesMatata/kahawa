# Kahawa

Kahawa is a cafe system for one shop: a public storefront and a staff floor at `/manage`. Customers order for pickup, delivery, or the table they scanned. Staff take payment, move orders through the kitchen, and keep the catalog.

## How it is built

One Django app, `kahawa`, on SQLite, with the clock set to Africa/Nairobi. The storefront and Manage are separate template shells. Customer accounts and staff logins are separate too. Staff actions are gated by roles, not by `is_staff` alone.

The bag lives in the browser. The server prices the order again on checkout, so the client total is only a preview. Listed prices already include VAT. Tax codes follow KRA eTIMS (`A`–`E`); the VAT line on a receipt is the tax inside the price, not an amount added on top.

M-Pesa is Daraja STK Push. `MPESA_MODE=mock` completes a payment locally. `live` uses the `MPESA_*` keys. SMS goes through Africa's Talking, or prints in the terminal when `SMS_PROVIDER=console`.

Manage sales export is a ReportLab PDF. Receipts and the kitchen ticket are print pages, and they use `static/images/kahawa-logo.png`. The eTIMS box on a receipt stays empty. `ETIMS_TIN`, `ETIMS_BHF_ID`, `ETIMS_DEVICE_SERIAL`, and `ETIMS_CMC_KEY` are loaded for a later OSCU connection and are not called yet.

Styles are Tailwind 3, compiled to `static/css/kahawa.css`. Pages do not load Tailwind from a CDN. `npm run build:css` rebuilds that file. Manage lists are tables on a wide screen and cards on a phone. Drawers rise from the bottom on a phone and from the right on a larger screen.

## Run

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

Copy `.env.example` to `.env` and keep `.env` out of git. `seed_kahawa` loads the demo catalog and prints the staff logins.
