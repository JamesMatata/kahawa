"""Helpers to record staff activity for the manage Team audit view."""

from __future__ import annotations


def log_staff_activity(user, action: str, summary: str, **meta) -> None:
    if not user or not getattr(user, 'is_authenticated', False):
        return
    from .models import StaffActivity

    StaffActivity.objects.create(
        actor=user,
        action=action,
        summary=(summary or '')[:255],
        meta=meta or {},
    )
