"""
Kahawa Manage — permission codes and role presets.

Roles are templates. Each staff member stores an effective `permissions` list
(union of selected roles, then admin can uncheck items on confirm).
"""

from __future__ import annotations

# code → (label, group)
PERMISSIONS: dict[str, tuple[str, str]] = {
    'ops.view': ('View live ops board', 'Operations'),
    'ops.create_order': ('Create counter / walk-in orders', 'Operations'),
    'ops.status.preparing': ('Mark orders Preparing', 'Operations'),
    'ops.status.ready': ('Mark orders Ready', 'Operations'),
    'ops.status.completed': ('Mark orders Completed', 'Operations'),
    'ops.cancel': ('Cancel orders', 'Operations'),
    'ops.collect_payment': ('Collect cash / mark paid in person', 'Operations'),
    'catalog.view': ('View products', 'Catalog'),
    'catalog.toggle': ('Mark products sold out / available', 'Catalog'),
    'catalog.edit': ('Create and edit products', 'Catalog'),
    'categories.manage': ('Manage categories', 'Catalog'),
    'tables.manage': ('Manage tables & QR links', 'Cafe'),
    'gifts.manage': ('Issue and manage gift cards', 'Cafe'),
    'team.manage': ('Manage team & permissions', 'Admin'),
    'analytics.view': ('View ops analytics', 'Admin'),
}

ALL_PERMISSION_CODES: list[str] = list(PERMISSIONS.keys())

# slug → (name, description, permission codes)
ROLE_PRESETS: dict[str, tuple[str, str, list[str]]] = {
    'admin': (
        'Admin',
        'Full access to Manage — owner / general manager.',
        list(ALL_PERMISSION_CODES),
    ),
    'manager': (
        'Manager',
        'Shift lead — ops, catalog, tables, gifts. No team admin.',
        [
            'ops.view',
            'ops.create_order',
            'ops.status.preparing',
            'ops.status.ready',
            'ops.status.completed',
            'ops.cancel',
            'ops.collect_payment',
            'catalog.view',
            'catalog.toggle',
            'catalog.edit',
            'categories.manage',
            'tables.manage',
            'gifts.manage',
            'analytics.view',
        ],
    ),
    'barista': (
        'Barista',
        'Drinks station — see orders and control preparing / ready.',
        [
            'ops.view',
            'ops.status.preparing',
            'ops.status.ready',
            'catalog.view',
            'catalog.toggle',
        ],
    ),
    'cashier': (
        'Cashier',
        'Counter — board, create orders, complete, collect payment, gifts.',
        [
            'ops.view',
            'ops.create_order',
            'ops.status.completed',
            'ops.cancel',
            'ops.collect_payment',
            'catalog.view',
            'gifts.manage',
            'analytics.view',
        ],
    ),
    'kitchen': (
        'Kitchen',
        'Food prep — preparing and ready only.',
        [
            'ops.view',
            'ops.status.preparing',
            'ops.status.ready',
            'catalog.view',
            'catalog.toggle',
        ],
    ),
    'runner': (
        'Runner',
        'Floor / dine-in — see board; payment optional (uncheck if cashier-only).',
        [
            'ops.view',
            'ops.status.ready',
            'ops.status.completed',
            'ops.collect_payment',
        ],
    ),
}


def permissions_by_group() -> list[tuple[str, list[dict]]]:
    """[(group, [{code, label}, ...]), ...] for UI checklists."""
    groups: dict[str, list[dict]] = {}
    for code, (label, group) in PERMISSIONS.items():
        groups.setdefault(group, []).append({'code': code, 'label': label})
    order = ['Operations', 'Catalog', 'Cafe', 'Admin']
    return [(g, groups[g]) for g in order if g in groups]


def merge_permission_codes(*code_lists) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for codes in code_lists:
        for code in codes or []:
            if code in PERMISSIONS and code not in seen:
                seen.add(code)
                out.append(code)
    return out


def role_preset_permissions(slug: str) -> list[str]:
    preset = ROLE_PRESETS.get(slug)
    return list(preset[2]) if preset else []
