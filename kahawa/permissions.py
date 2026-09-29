"""Staff / admin role helpers for the custom management dashboard."""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .permissions_catalog import ALL_PERMISSION_CODES, permissions_by_group

STAFF_LOGIN_URL = '/manage/login/'


def get_staff_profile(user):
    if not user.is_authenticated:
        return None
    return getattr(user, 'staff_profile', None)


def is_cafe_staff(user) -> bool:
    """Active staff with is_staff flag."""
    if not user.is_authenticated or not user.is_staff:
        return False
    profile = get_staff_profile(user)
    if profile is not None and not profile.is_active:
        return False
    return True


def user_permissions(user) -> set[str]:
    if not is_cafe_staff(user):
        return set()
    if user.is_superuser:
        return set(ALL_PERMISSION_CODES)
    profile = get_staff_profile(user)
    if profile is None:
        # Legacy staff without profile — treat as ops-only
        return {'ops.view', 'ops.status.preparing', 'ops.status.ready', 'catalog.view'}
    return set(profile.permissions or [])


def has_perm(user, code: str) -> bool:
    return code in user_permissions(user)


def is_cafe_admin(user) -> bool:
    """Can manage team / full admin capabilities."""
    return has_perm(user, 'team.manage')


def staff_login_required(view_func):
    """Require cafe staff; redirect to custom staff login."""

    @login_required(login_url=STAFF_LOGIN_URL)
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_cafe_staff(request.user):
            return HttpResponseForbidden('Staff access required.')
        return view_func(request, *args, **kwargs)

    return _wrapped


def permission_required(*codes, any_of: bool = False):
    """Require one (any_of) or all listed permission codes."""

    def decorator(view_func):
        @staff_login_required
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            perms = user_permissions(request.user)
            ok = (
                any(c in perms for c in codes)
                if any_of
                else all(c in perms for c in codes)
            )
            if not ok:
                if 'ops.view' in perms:
                    return redirect('kahawa:staff_dashboard')
                if 'catalog.view' in perms:
                    return redirect('kahawa:manage_products')
                return HttpResponseForbidden('You do not have permission for this.')
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def admin_required(view_func):
    """Require team.manage permission."""
    return permission_required('team.manage')(view_func)


def manage_nav_context(request) -> dict:
    """Shared sidebar context for management templates."""
    profile = get_staff_profile(request.user)
    perms = user_permissions(request.user)
    role_label = 'Admin' if request.user.is_superuser else 'Staff'
    if profile:
        role_label = profile.role_label()
    return {
        'is_admin': 'team.manage' in perms,
        'perms': perms,
        'can': {code: (code in perms) for code in ALL_PERMISSION_CODES},
        'staff_label': (
            profile.label()
            if profile
            else (request.user.get_full_name() or request.user.get_username())
        ),
        'staff_role_label': role_label,
        'permission_groups': permissions_by_group(),
    }
