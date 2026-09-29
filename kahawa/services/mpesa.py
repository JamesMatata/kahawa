"""
M-Pesa Daraja STK Push with mock fallback for local development.

Set MPESA_MODE=live with Daraja credentials for production.
Default MPESA_MODE=mock keeps the existing demo flow.

Callback hardening:
- Optional path secret (MPESA_CALLBACK_SECRET) must match
- CheckoutRequestID must have been registered when STK was started
- Amount in callback must match expected amount when present
"""

from __future__ import annotations

import base64
import hmac
import logging
import secrets
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

logger = logging.getLogger(__name__)

TOKEN_CACHE_KEY = 'kahawa_mpesa_access_token'
PENDING_STK_PREFIX = 'kahawa_stk_pending:'
PENDING_STK_TTL = 60 * 30  # 30 minutes


def mpesa_mode() -> str:
    return (getattr(settings, 'MPESA_MODE', 'mock') or 'mock').lower()


def is_live() -> bool:
    return mpesa_mode() == 'live' and bool(
        getattr(settings, 'MPESA_CONSUMER_KEY', '')
        and getattr(settings, 'MPESA_CONSUMER_SECRET', '')
        and getattr(settings, 'MPESA_SHORTCODE', '')
        and getattr(settings, 'MPESA_PASSKEY', '')
    )


def callback_secret() -> str:
    return (getattr(settings, 'MPESA_CALLBACK_SECRET', '') or '').strip()


def _base_url() -> str:
    env = (getattr(settings, 'MPESA_ENV', 'sandbox') or 'sandbox').lower()
    if env == 'production':
        return 'https://api.safaricom.co.ke'
    return 'https://sandbox.safaricom.co.ke'


def _get_access_token() -> str | None:
    cached = cache.get(TOKEN_CACHE_KEY)
    if cached:
        return cached

    key = settings.MPESA_CONSUMER_KEY
    secret = settings.MPESA_CONSUMER_SECRET
    url = f'{_base_url()}/oauth/v1/generate?grant_type=client_credentials'
    try:
        res = requests.get(url, auth=(key, secret), timeout=20)
        res.raise_for_status()
        token = res.json().get('access_token')
        if token:
            cache.set(TOKEN_CACHE_KEY, token, timeout=3500)
        return token
    except Exception:
        logger.exception('Failed to obtain M-Pesa access token')
        return None


def _stk_password(timestamp: str) -> str:
    raw = f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def _callback_url() -> str:
    configured = (getattr(settings, 'MPESA_CALLBACK_URL', '') or '').strip()
    if configured:
        return configured
    site = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
    secret = callback_secret()
    if secret:
        path = reverse('kahawa:mpesa_callback_secure', kwargs={'secret': secret})
    else:
        path = reverse('kahawa:mpesa_callback')
    return f'{site}{path}'


def _normalize_msisdn(phone: str) -> str:
    digits = ''.join(c for c in (phone or '') if c.isdigit())
    if digits.startswith('254') and len(digits) >= 12:
        return digits[:12]
    if digits.startswith('0') and len(digits) >= 10:
        return f'254{digits[1:10]}'
    if len(digits) == 9 and digits.startswith(('7', '1')):
        return f'254{digits}'
    return digits


def register_pending_stk(
    checkout_request_id: str,
    *,
    amount: Decimal | int | float,
    kind: str,
    ref_id: int | None = None,
) -> None:
    """Remember a CheckoutRequestID we issued so callbacks can be verified."""
    if not checkout_request_id:
        return
    cache.set(
        f'{PENDING_STK_PREFIX}{checkout_request_id}',
        {
            'amount': int(Decimal(str(amount)).quantize(Decimal('1'))),
            'kind': kind,
            'ref_id': ref_id,
            'nonce': secrets.token_hex(8),
        },
        timeout=PENDING_STK_TTL,
    )


def pop_pending_stk(checkout_request_id: str) -> dict | None:
    key = f'{PENDING_STK_PREFIX}{checkout_request_id}'
    data = cache.get(key)
    if data is not None:
        cache.delete(key)
    return data


def verify_callback_secret(provided: str | None) -> bool:
    """
    When MPESA_CALLBACK_SECRET is set, the path segment must match.
    When unset (local mock), allow the open URL for convenience.
    """
    expected = callback_secret()
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(str(provided), expected)


def verify_callback_checkout(checkout_request_id: str, amount=None) -> tuple[bool, str]:
    """
    Accept only CheckoutRequestIDs we registered (or that still exist on an
    unpaid order/gift — covers process restarts within TTL miss).
    """
    if not checkout_request_id:
        return False, 'Missing CheckoutRequestID'

    pending = cache.get(f'{PENDING_STK_PREFIX}{checkout_request_id}')
    if pending:
        if amount is not None:
            try:
                got = int(Decimal(str(amount)).quantize(Decimal('1')))
            except Exception:
                got = None
            expected = int(pending.get('amount') or 0)
            if got is not None and expected and abs(got - expected) > 0:
                return False, 'Amount mismatch'
        return True, ''

    # Fallback: known unpaid order / gift still awaiting this checkout id
    from kahawa.models import GiftCard, Order

    order = Order.objects.filter(
        mpesa_checkout_request_id=checkout_request_id,
        payment_status=Order.PaymentStatus.PENDING,
    ).first()
    if order:
        if amount is not None:
            try:
                got = int(Decimal(str(amount)).quantize(Decimal('1')))
                expected = int(Decimal(str(order.total_amount)).quantize(Decimal('1')))
                if abs(got - expected) > 0:
                    return False, 'Amount mismatch'
            except Exception:
                pass
        return True, ''

    gift = GiftCard.objects.filter(
        mpesa_checkout_request_id=checkout_request_id,
        payment_status='PENDING',
    ).first()
    if gift:
        if amount is not None:
            try:
                got = int(Decimal(str(amount)).quantize(Decimal('1')))
                expected = int(Decimal(str(gift.initial_balance)).quantize(Decimal('1')))
                if abs(got - expected) > 0:
                    return False, 'Amount mismatch'
            except Exception:
                pass
        return True, ''

    return False, 'Unknown CheckoutRequestID'


def initiate_stk_push(
    *,
    phone: str,
    order=None,
    amount=None,
    account_ref: str | None = None,
    description: str | None = None,
    kind: str = 'order',
    ref_id: int | None = None,
) -> dict[str, Any]:
    """
    Start STK Push for an order or arbitrary amount (e.g. gift card).
    Returns {ok, checkout_request_id, error?, mock?}
    """
    if order is not None:
        amount = order.total_amount if amount is None else amount
        account_ref = account_ref or getattr(order, 'order_code', '') or 'KAHAWA'
        description = description or f'Kahawa {account_ref}'
        phone = phone or getattr(order, 'phone', '')
        ref_id = getattr(order, 'id', None) if ref_id is None else ref_id
        kind = 'order'

    pay_amount = int(Decimal(str(amount or 0)).quantize(Decimal('1')))
    if pay_amount < 1:
        return {'ok': False, 'error': 'Invalid payment amount.'}

    ref = (account_ref or 'KAHAWA')[:12]
    desc = (description or f'Kahawa {ref}')[:20]

    msisdn = _normalize_msisdn(phone or '')
    if not msisdn.startswith('254') or len(msisdn) != 12:
        return {'ok': False, 'error': 'Enter a valid M-Pesa phone number.'}

    if not is_live():
        checkout_id = f'ws_{uuid.uuid4().hex[:16]}'
        register_pending_stk(
            checkout_id, amount=pay_amount, kind=kind, ref_id=ref_id
        )
        return {
            'ok': True,
            'checkout_request_id': checkout_id,
            'mock': True,
            'customer_message': 'Demo mode: confirm on this screen (no real STK).',
        }

    if is_live() and not callback_secret() and not (
        getattr(settings, 'MPESA_CALLBACK_URL', '') or ''
    ).strip():
        logger.warning(
            'MPESA_CALLBACK_SECRET is empty — set it before going live.'
        )

    token = _get_access_token()
    if not token:
        return {'ok': False, 'error': 'Payment service unavailable. Please try again.'}

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    payload = {
        'BusinessShortCode': settings.MPESA_SHORTCODE,
        'Password': _stk_password(timestamp),
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': pay_amount,
        'PartyA': msisdn,
        'PartyB': settings.MPESA_SHORTCODE,
        'PhoneNumber': msisdn,
        'CallBackURL': _callback_url(),
        'AccountReference': ref,
        'TransactionDesc': desc,
    }

    url = f'{_base_url()}/mpesa/stkpush/v1/processrequest'
    try:
        res = requests.post(
            url,
            json=payload,
            headers={'Authorization': f'Bearer {token}'},
            timeout=30,
        )
        data = res.json()
        if res.status_code >= 400 or data.get('ResponseCode') not in ('0', 0):
            logger.warning('STK push rejected: %s', data)
            return {
                'ok': False,
                'error': data.get('errorMessage')
                or data.get('ResponseDescription')
                or 'Could not send M-Pesa prompt. Try again.',
            }
        checkout_id = data.get('CheckoutRequestID') or ''
        if not checkout_id:
            return {'ok': False, 'error': 'Could not start payment. Try again.'}
        register_pending_stk(
            checkout_id, amount=pay_amount, kind=kind, ref_id=ref_id
        )
        return {
            'ok': True,
            'checkout_request_id': checkout_id,
            'mock': False,
            'customer_message': data.get('CustomerMessage')
            or 'Check your phone for the M-Pesa prompt.',
        }
    except Exception:
        logger.exception('STK push request failed')
        return {'ok': False, 'error': 'Network error starting payment. Try again.'}


def parse_callback(body: dict) -> dict[str, Any]:
    """Normalize Daraja STK callback body."""
    try:
        result = body.get('Body', {}).get('stkCallback', {})
        checkout_id = result.get('CheckoutRequestID') or ''
        result_code = result.get('ResultCode')
        metadata = {}
        items = (result.get('CallbackMetadata') or {}).get('Item') or []
        for item in items:
            name = item.get('Name')
            if name:
                metadata[name] = item.get('Value')
        return {
            'checkout_request_id': checkout_id,
            'result_code': result_code,
            'success': result_code in (0, '0'),
            'receipt': str(metadata.get('MpesaReceiptNumber') or ''),
            'amount': metadata.get('Amount'),
            'phone': str(metadata.get('PhoneNumber') or ''),
        }
    except Exception:
        logger.exception('Failed to parse M-Pesa callback')
        return {'checkout_request_id': '', 'success': False, 'result_code': -1}
