"""Simple cache-based rate limiting for public auth/payment endpoints."""

from __future__ import annotations

import functools
from typing import Callable

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse


def _client_ip(request: HttpRequest) -> str:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR') or 'unknown'


def rate_limit(
    *,
    key: str,
    limit: int = 20,
    window: int = 60,
    methods: tuple[str, ...] | None = ('POST',),
):
    """
    Limit requests per client IP.

    key: namespace for the bucket (e.g. 'login', 'start_payment')
    limit: max hits inside the window
    window: seconds
    methods: HTTP methods to throttle (None = all)
    """

    def decorator(view: Callable):
        @functools.wraps(view)
        def wrapped(request: HttpRequest, *args, **kwargs):
            method = (request.method or 'GET').upper()
            if methods is not None and method not in methods:
                return view(request, *args, **kwargs)

            ip = _client_ip(request)
            cache_key = f'kahawa_rl:{key}:{ip}'
            count = cache.get(cache_key)
            if count is None:
                cache.set(cache_key, 1, timeout=window)
            elif int(count) >= limit:
                wants_json = (
                    'application/json' in (request.headers.get('Accept') or '')
                    or request.content_type == 'application/json'
                    or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                )
                if wants_json or method in ('POST',) and 'json' in (
                    request.content_type or ''
                ):
                    return JsonResponse(
                        {
                            'ok': False,
                            'error': 'Too many attempts. Please wait a moment and try again.',
                        },
                        status=429,
                    )
                return HttpResponse(
                    'Too many attempts. Please wait a moment and try again.',
                    status=429,
                    content_type='text/plain; charset=utf-8',
                )
            else:
                try:
                    cache.incr(cache_key)
                except ValueError:
                    cache.set(cache_key, 1, timeout=window)

            return view(request, *args, **kwargs)

        return wrapped

    return decorator
