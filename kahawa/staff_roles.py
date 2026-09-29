"""Ensure system StaffRole rows match permissions_catalog.ROLE_PRESETS."""

from __future__ import annotations

from .permissions_catalog import ROLE_PRESETS


def ensure_system_roles():
    from .models import StaffRole

    order = {slug: i for i, slug in enumerate(ROLE_PRESETS)}
    for slug, (name, description, perms) in ROLE_PRESETS.items():
        StaffRole.objects.update_or_create(
            slug=slug,
            defaults={
                'name': name,
                'description': description,
                'default_permissions': list(perms),
                'is_system': True,
                'sort_order': order.get(slug, 99),
            },
        )
    return StaffRole.objects.filter(slug__in=ROLE_PRESETS.keys())


def parse_permission_codes(raw) -> list[str]:
    from .permissions_catalog import PERMISSIONS, merge_permission_codes

    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    return merge_permission_codes(list(raw))


def apply_roles_and_permissions(profile, role_slugs, permission_codes) -> None:
    from .models import StaffRole
    from .permissions_catalog import ALL_PERMISSION_CODES

    roles = list(StaffRole.objects.filter(slug__in=role_slugs))
    profile.roles.set(roles)
    codes = parse_permission_codes(permission_codes)
    if not codes and roles:
        merged = []
        for r in roles:
            merged.extend(r.default_permissions or [])
        codes = parse_permission_codes(merged)
    # Admin role always gets full set
    if any(r.slug == 'admin' for r in roles):
        codes = list(ALL_PERMISSION_CODES)
    profile.permissions = codes
    profile.save(update_fields=['permissions'])
    # Mirror Django flags
    user = profile.user
    user.is_superuser = 'team.manage' in codes
    user.is_staff = True
    user.save(update_fields=['is_superuser', 'is_staff'])
