"""Account auth: login, register (SMS OTP), password reset (SMS OTP)."""

from __future__ import annotations

import re

from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .models import CustomerProfile, Order
from .ratelimit import rate_limit
from .services.otp import create_and_send_otp, verify_otp
from .services.sms import format_kenyan_phone

User = get_user_model()

REGISTER_SESSION_KEY = 'kahawa_register_pending'
RESET_SESSION_KEY = 'kahawa_reset_pending'
KENYAN_PHONE_RE = re.compile(r'^(?:0[17]\d{8}|\+?254[17]\d{8})$')


def _validate_kenyan_phone(phone: str) -> str | None:
    cleaned = (phone or '').strip().replace(' ', '')
    if not KENYAN_PHONE_RE.match(cleaned):
        return None
    return format_kenyan_phone(cleaned)


def _split_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or '').strip().split(None, 1)
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], parts[1]


def _username_from_phone(phone: str) -> str:
    return format_kenyan_phone(phone).lstrip('+')


def _claim_guest_orders(user, phone: str) -> None:
    Order.objects.filter(user__isnull=True, phone=phone).update(user=user)


def _get_or_create_profile(user) -> CustomerProfile:
    profile, _ = CustomerProfile.objects.get_or_create(user=user)
    return profile


@rate_limit(key='login', limit=12, window=60)
@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('kahawa:orders')

    error = ''
    phone = ''
    next_url = request.GET.get('next') or request.POST.get('next') or ''

    if request.method == 'POST':
        phone_raw = (request.POST.get('phone') or '').strip()
        password = request.POST.get('password') or ''
        phone = phone_raw
        next_url = request.POST.get('next') or ''

        formatted = _validate_kenyan_phone(phone_raw)
        if not formatted:
            error = 'Enter a valid Kenyan phone number (07… or 01…).'
        elif not password:
            error = 'Enter your password.'
        else:
            username = _username_from_phone(formatted)
            user = authenticate(request, username=username, password=password)
            if user is None:
                profile = (
                    CustomerProfile.objects.select_related('user')
                    .filter(phone=formatted)
                    .first()
                )
                if profile:
                    user = authenticate(
                        request,
                        username=profile.user.get_username(),
                        password=password,
                    )
            if user is None:
                error = 'Incorrect phone or password.'
            else:
                login(request, user)
                _claim_guest_orders(user, formatted)
                if next_url and next_url.startswith('/'):
                    return redirect(next_url)
                return redirect('kahawa:orders')

    return render(
        request,
        'accounts/login.html',
        {'error': error, 'phone': phone, 'next': next_url},
    )


@rate_limit(key='register', limit=8, window=60)
@require_http_methods(['GET', 'POST'])
def register_view(request):
    if request.user.is_authenticated:
        return redirect('kahawa:orders')

    error = ''
    form = {
        'full_name': '',
        'phone': '',
    }

    if request.method == 'POST':
        form['full_name'] = (request.POST.get('full_name') or '').strip()
        form['phone'] = (request.POST.get('phone') or '').strip()
        password = request.POST.get('password') or ''
        password2 = request.POST.get('password2') or ''

        phone = _validate_kenyan_phone(form['phone'])
        if not form['full_name']:
            error = 'Enter your full name.'
        elif not phone:
            error = 'Enter a valid Kenyan phone number (07… or 01…).'
        elif CustomerProfile.objects.filter(phone=phone).exists():
            error = 'An account with this phone already exists. Sign in instead.'
        elif User.objects.filter(username=_username_from_phone(phone)).exists():
            error = 'An account with this phone already exists. Sign in instead.'
        elif not password or len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif password != password2:
            error = 'Passwords do not match.'
        else:
            try:
                validate_password(password)
            except ValidationError as exc:
                error = ' '.join(exc.messages)
            else:
                ok, otp_error = create_and_send_otp(phone, 'register')
                if not ok:
                    error = otp_error
                else:
                    request.session[REGISTER_SESSION_KEY] = {
                        'full_name': form['full_name'],
                        'phone': phone,
                        'password': password,
                    }
                    return redirect('kahawa:register_verify')

    return render(request, 'accounts/register.html', {'error': error, 'form': form})


@rate_limit(key='register_verify', limit=20, window=60)
@require_http_methods(['GET', 'POST'])
def register_verify_view(request):
    pending = request.session.get(REGISTER_SESSION_KEY)
    if not pending:
        return redirect('kahawa:register')
    if request.user.is_authenticated:
        return redirect('kahawa:orders')

    error = ''
    info = ''
    phone = pending.get('phone', '')

    if request.method == 'POST':
        action = request.POST.get('action') or 'verify'
        if action == 'resend':
            ok, otp_error = create_and_send_otp(phone, 'register')
            if ok:
                info = 'A new code was sent.'
            else:
                error = otp_error
        else:
            code = (request.POST.get('otp') or '').strip()
            ok, otp_error = verify_otp(phone, 'register', code)
            if not ok:
                error = otp_error
            else:
                first, last = _split_name(pending.get('full_name', ''))
                username = _username_from_phone(phone)
                try:
                    with transaction.atomic():
                        user = User.objects.create_user(
                            username=username,
                            password=pending.get('password'),
                            first_name=first,
                            last_name=last,
                        )
                        profile = _get_or_create_profile(user)
                        profile.phone = phone
                        profile.save()
                        _claim_guest_orders(user, phone)
                except Exception:
                    error = 'Could not create your account. Please try again.'
                else:
                    request.session.pop(REGISTER_SESSION_KEY, None)
                    login(request, user)
                    return redirect('kahawa:orders')

    return render(
        request,
        'accounts/register_verify.html',
        {'error': error, 'info': info, 'phone': phone},
    )


@rate_limit(key='password_reset', limit=8, window=60)
@require_http_methods(['GET', 'POST'])
def password_reset_request_view(request):
    if request.user.is_authenticated:
        return redirect('kahawa:orders')

    error = ''
    phone = ''

    if request.method == 'POST':
        phone_raw = (request.POST.get('phone') or '').strip()
        phone = phone_raw
        formatted = _validate_kenyan_phone(phone_raw)
        if not formatted:
            error = 'Enter a valid Kenyan phone number (07… or 01…).'
        else:
            profile = CustomerProfile.objects.filter(phone=formatted).first()
            if profile:
                ok, otp_error = create_and_send_otp(formatted, 'reset')
                if not ok:
                    error = otp_error
                else:
                    request.session[RESET_SESSION_KEY] = {'phone': formatted}
                    return redirect('kahawa:password_reset_verify')
            else:
                request.session[RESET_SESSION_KEY] = {'phone': formatted}
                return redirect('kahawa:password_reset_verify')

    return render(
        request,
        'accounts/password_reset.html',
        {'error': error, 'phone': phone},
    )


@rate_limit(key='password_reset_verify', limit=20, window=60)
@require_http_methods(['GET', 'POST'])
def password_reset_verify_view(request):
    pending = request.session.get(RESET_SESSION_KEY)
    if not pending:
        return redirect('kahawa:password_reset')

    error = ''
    info = ''
    phone = pending.get('phone', '')
    verified = bool(pending.get('verified'))

    if request.method == 'POST':
        action = request.POST.get('action') or 'verify'

        if action == 'resend':
            profile = CustomerProfile.objects.filter(phone=phone).first()
            if profile:
                ok, otp_error = create_and_send_otp(phone, 'reset')
                if ok:
                    info = 'A new code was sent.'
                else:
                    error = otp_error
            else:
                info = 'A new code was sent.'
            verified = False
        elif action == 'set_password':
            if not pending.get('verified'):
                return redirect('kahawa:password_reset_verify')
            password = request.POST.get('password') or ''
            password2 = request.POST.get('password2') or ''
            if not password or len(password) < 8:
                error = 'Password must be at least 8 characters.'
                verified = True
            elif password != password2:
                error = 'Passwords do not match.'
                verified = True
            else:
                try:
                    validate_password(password)
                except ValidationError as exc:
                    error = ' '.join(exc.messages)
                    verified = True
                else:
                    profile = (
                        CustomerProfile.objects.filter(phone=phone)
                        .select_related('user')
                        .first()
                    )
                    if not profile:
                        error = 'No account found for this phone.'
                        verified = True
                    else:
                        user = profile.user
                        user.set_password(password)
                        user.save(update_fields=['password'])
                        request.session.pop(RESET_SESSION_KEY, None)
                        login(request, user)
                        return redirect('kahawa:orders')
        else:
            code = (request.POST.get('otp') or '').strip()
            ok, otp_error = verify_otp(phone, 'reset', code)
            if not ok:
                error = otp_error
            else:
                pending['verified'] = True
                request.session[RESET_SESSION_KEY] = pending
                verified = True

    return render(
        request,
        'accounts/password_reset_verify.html',
        {'error': error, 'info': info, 'phone': phone, 'verified': verified},
    )


@login_required(login_url='/accounts/login/')
@require_http_methods(['GET', 'POST'])
def profile_view(request):
    """Edit account details: name, phone, default location, password."""
    user = request.user
    profile = _get_or_create_profile(user)
    error = ''

    if request.method == 'POST':
        action = (request.POST.get('action') or 'details').strip()

        if action == 'password':
            current = request.POST.get('current_password') or ''
            new_password = request.POST.get('new_password') or ''
            confirm = request.POST.get('confirm_password') or ''
            if not user.check_password(current):
                error = 'Current password is incorrect.'
            elif not new_password:
                error = 'Enter a new password.'
            elif new_password != confirm:
                error = 'New passwords do not match.'
            else:
                try:
                    validate_password(new_password, user)
                except ValidationError as exc:
                    error = ' '.join(exc.messages)
                else:
                    user.set_password(new_password)
                    user.save(update_fields=['password'])
                    update_session_auth_hash(request, user)
                    messages.success(request, 'Password updated.')
                    return redirect('kahawa:profile')
        else:
            full_name = (request.POST.get('full_name') or '').strip()
            first_name = (request.POST.get('first_name') or '').strip()
            last_name = (request.POST.get('last_name') or '').strip()
            if full_name:
                first_name, last_name = _split_name(full_name)
            phone_raw = (request.POST.get('phone') or '').strip()
            location = (request.POST.get('default_location') or '').strip()

            formatted = None
            if phone_raw:
                formatted = _validate_kenyan_phone(phone_raw)
                if not formatted:
                    error = 'Enter a valid Kenyan phone number (07… or 01…).'
                else:
                    taken = (
                        CustomerProfile.objects.filter(phone=formatted)
                        .exclude(user=user)
                        .exists()
                    )
                    if taken:
                        error = 'That phone number is already linked to another account.'

            if not error:
                user.first_name = first_name
                user.last_name = last_name
                user.save(update_fields=['first_name', 'last_name'])
                if formatted is not None:
                    profile.phone = formatted
                profile.default_location = location
                profile.save(update_fields=['phone', 'default_location'])
                messages.success(request, 'Profile saved.')
                return redirect('kahawa:profile')

    full_name = user.get_full_name().strip() or ''
    password_error = error if request.method == 'POST' and (request.POST.get('action') or '') == 'password' else ''
    return render(
        request,
        'accounts/profile.html',
        {
            'error': error,
            'password_error': password_error,
            'profile': profile,
            'full_name': full_name,
            'phone_display': profile.phone or '',
        },
    )


@require_http_methods(['POST'])
def logout_view(request):
    logout(request)
    return redirect('kahawa:home')
