"""SMS OTP helpers for Kahawa account flows."""

from __future__ import annotations

import random
import logging

from django.core.cache import cache

from .sms import format_kenyan_phone, send_sms

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 10 * 60
OTP_RESEND_COOLDOWN = 45
OTP_MAX_ATTEMPTS = 5


def _otp_key(purpose: str, phone: str) -> str:
    return f'kahawa_otp:{purpose}:{phone}'


def _attempts_key(purpose: str, phone: str) -> str:
    return f'kahawa_otp_attempts:{purpose}:{phone}'


def _cooldown_key(purpose: str, phone: str) -> str:
    return f'kahawa_otp_cooldown:{purpose}:{phone}'


def create_and_send_otp(phone: str, purpose: str) -> tuple[bool, str]:
    """
    Generate a 6-digit OTP, cache it, and SMS it.
    Returns (ok, error_message).
    """
    try:
        formatted = format_kenyan_phone(phone)
    except Exception:
        return False, 'Enter a valid Kenyan phone number.'

    if cache.get(_cooldown_key(purpose, formatted)):
        return False, 'Please wait a moment before requesting another code.'

    code = f'{random.randint(0, 999999):06d}'
    cache.set(_otp_key(purpose, formatted), code, timeout=OTP_TTL_SECONDS)
    cache.set(_attempts_key(purpose, formatted), 0, timeout=OTP_TTL_SECONDS)
    cache.set(_cooldown_key(purpose, formatted), 1, timeout=OTP_RESEND_COOLDOWN)

    if purpose == 'register':
        message = f'Your Kahawa verification code is {code}. It expires in 10 minutes.'
    elif purpose == 'reset':
        message = f'Your Kahawa password reset code is {code}. It expires in 10 minutes.'
    else:
        message = f'Your Kahawa code is {code}. It expires in 10 minutes.'

    result = send_sms(formatted, message)
    if result.get('status') in ('error', 'skipped'):
        return False, 'Could not send the SMS. Please try again.'

    logger.info('OTP sent for %s to %s', purpose, formatted)
    return True, ''


def verify_otp(phone: str, purpose: str, code: str) -> tuple[bool, str]:
    try:
        formatted = format_kenyan_phone(phone)
    except Exception:
        return False, 'Enter a valid Kenyan phone number.'

    stored = cache.get(_otp_key(purpose, formatted))
    if not stored:
        return False, 'Code expired or not found. Request a new one.'

    attempts = int(cache.get(_attempts_key(purpose, formatted)) or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        cache.delete(_otp_key(purpose, formatted))
        return False, 'Too many attempts. Request a new code.'

    if str(code).strip() != str(stored):
        cache.set(_attempts_key(purpose, formatted), attempts + 1, timeout=OTP_TTL_SECONDS)
        return False, 'Incorrect code. Please try again.'

    cache.delete(_otp_key(purpose, formatted))
    cache.delete(_attempts_key(purpose, formatted))
    return True, ''
