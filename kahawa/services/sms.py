"""
SMS notification utilities for Kahawa order confirmations.

Provider is selected via SMS_PROVIDER (africastalking | console).
Failures are logged and never raised to callers.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


def format_kenyan_phone(phone: str) -> str:
    """Normalize a Kenyan phone number to E.164 (+254…)."""
    digits = re.sub(r'\D', '', phone or '')

    if digits.startswith('254') and len(digits) >= 12:
        digits = digits[:12]
    elif digits.startswith('0') and len(digits) >= 10:
        digits = f'254{digits[1:10]}'
    elif len(digits) == 9 and digits.startswith('7'):
        digits = f'254{digits}'
    elif digits.startswith('254'):
        pass
    else:
        # Best-effort: strip leading zeros and prefix country code.
        digits = f"254{digits.lstrip('0')}"

    return f'+{digits}'


def _format_amount(amount: Decimal | float | int | str) -> str:
    value = Decimal(str(amount)).quantize(Decimal('0.01'))
    # Drop trailing .00 for cleaner SMS copy when whole shillings.
    if value == value.to_integral_value():
        return f'{int(value):,}'
    return f'{value:,.2f}'


def build_order_confirmation_message(order: Any) -> str:
    site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
    track_url = f"{site_url}/track/?code={order.order_code}"
    amount = _format_amount(order.total_amount)

    return (
        f'Habari {order.customer_name}! Your Kahawa order #{order.order_code} '
        f'has been received! Amount: KSh {amount}. Track your order here: '
        f'{track_url}. Fresh brew coming up!'
    )


def _has_africastalking_credentials() -> bool:
    username = getattr(settings, 'AT_USERNAME', '') or ''
    api_key = getattr(settings, 'AT_API_KEY', '') or ''
    return bool(username.strip() and api_key.strip())


def _should_use_console() -> bool:
    provider = (getattr(settings, 'SMS_PROVIDER', 'console') or 'console').lower()
    if provider == 'console':
        return True
    if getattr(settings, 'DEBUG', False) and not _has_africastalking_credentials():
        return True
    return False


def _print_console_sms(phone: str, message: str) -> dict[str, Any]:
    border = '=' * 60
    output = (
        f'\n{border}\n'
        f'[Kahawa SMS · console]\n'
        f'To: {phone}\n'
        f'Message:\n{message}\n'
        f'{border}\n'
    )
    print(output)
    logger.info('SMS console fallback to %s', phone)
    return {'status': 'console', 'to': phone, 'message': message}


def _send_via_africastalking(phone: str, message: str) -> dict[str, Any]:
    import africastalking

    username = settings.AT_USERNAME
    api_key = settings.AT_API_KEY
    sender_id = (getattr(settings, 'AT_SENDER_ID', '') or '').strip() or None

    africastalking.initialize(username, api_key)
    sms = africastalking.SMS

    if sender_id:
        response = sms.send(message, [phone], sender_id=sender_id)
    else:
        response = sms.send(message, [phone])

    logger.info('Africa\'s Talking SMS sent to %s: %s', phone, response)
    return {'status': 'sent', 'to': phone, 'provider': 'africastalking', 'response': response}


def send_sms(phone: str, message: str) -> dict[str, Any]:
    """
    Send a raw SMS. Never raises — network/API errors are logged.
    """
    try:
        formatted_phone = format_kenyan_phone(phone)
        if not formatted_phone or formatted_phone == '+254':
            logger.warning('Skipping SMS: invalid phone %r', phone)
            return {'status': 'skipped', 'reason': 'invalid_phone'}

        if _should_use_console():
            return _print_console_sms(formatted_phone, message)

        provider = (getattr(settings, 'SMS_PROVIDER', 'africastalking') or '').lower()
        if provider == 'africastalking':
            return _send_via_africastalking(formatted_phone, message)

        logger.warning('Unknown SMS_PROVIDER %r — using console fallback', provider)
        return _print_console_sms(formatted_phone, message)
    except Exception:
        logger.exception('Failed to send SMS to %r', phone)
        return {'status': 'error', 'to': phone}


def send_order_confirmation_sms(order: Any) -> dict[str, Any]:
    """
    Notify a customer that their Kahawa order was received.

    Safe for use in order-creation flows: exceptions are caught and logged.
    """
    try:
        message = build_order_confirmation_message(order)
        return send_sms(order.phone, message)
    except Exception:
        logger.exception(
            'Failed to send order confirmation SMS for order %s',
            getattr(order, 'order_code', None),
        )
        return {'status': 'error', 'order_code': getattr(order, 'order_code', None)}


def build_order_cancelled_message(order: Any, reason: str = '') -> str:
    site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
    track_url = f"{site_url}/track/?code={order.order_code}"
    base = (
        f'Habari {order.customer_name}. Your Kahawa order #{order.order_code} '
        f'has been cancelled.'
    )
    if reason:
        base += f' Reason: {reason}.'
    if getattr(order, 'payment_status', None) == 'REFUNDED':
        base += ' A refund will be processed for your M-Pesa payment.'
    base += f' Details: {track_url}'
    return base


def send_order_cancelled_sms(order: Any, reason: str = '') -> dict[str, Any]:
    """Notify a customer that their order was cancelled. Never raises."""
    try:
        message = build_order_cancelled_message(
            order,
            reason=reason or getattr(order, 'cancel_reason', '') or '',
        )
        return send_sms(order.phone, message)
    except Exception:
        logger.exception(
            'Failed to send cancel SMS for order %s',
            getattr(order, 'order_code', None),
        )
        return {'status': 'error', 'order_code': getattr(order, 'order_code', None)}
