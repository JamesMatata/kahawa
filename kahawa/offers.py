"""Package lines for storefront and counter orders."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.http import JsonResponse

from .models import Package


def live_packages():
    packages = Package.objects.prefetch_related('items__product').order_by('name')
    return [package for package in packages if package.is_live()]


def component_snapshot(package: Package) -> list[dict]:
    rows = []
    for row in package.items.select_related('product'):
        rows.append(
            {
                'name': row.product.name,
                'quantity': row.quantity,
            }
        )
    return rows


def package_customization(package: Package) -> dict:
    return {'components': component_snapshot(package)}


def resolve_package_line(raw: dict):
    """
    Validate a cart row that is a package.
    Returns (line_dict, None) or (None, JsonResponse).
    """
    package_id = raw.get('packageId') or raw.get('package_id')
    if not package_id:
        return None, None
    try:
        quantity = int(raw.get('quantity') or 0)
        package_id = int(package_id)
    except (TypeError, ValueError):
        return None, JsonResponse({'ok': False, 'error': 'Invalid package.'}, status=400)
    if quantity < 1:
        return None, JsonResponse({'ok': False, 'error': 'Invalid item quantity.'}, status=400)

    package = (
        Package.objects.prefetch_related('items__product')
        .filter(pk=package_id)
        .first()
    )
    if not package or not package.is_live():
        return None, JsonResponse(
            {'ok': False, 'error': 'That offer is no longer available.'},
            status=400,
        )
    if not package.items.exists():
        return None, JsonResponse(
            {'ok': False, 'error': 'That offer has no items.'},
            status=400,
        )

    expected = Decimal(package.price).quantize(Decimal('0.01'))
    client_unit = raw.get('unitPrice', raw.get('unit_price'))
    if client_unit is not None:
        try:
            client_decimal = Decimal(str(client_unit)).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            return None, JsonResponse(
                {'ok': False, 'error': 'Invalid item price.'},
                status=400,
            )
        if client_decimal != expected:
            return None, JsonResponse(
                {
                    'ok': False,
                    'error': (
                        f'Price mismatch for {package.name}. '
                        'Please refresh your bag and try again.'
                    ),
                },
                status=400,
            )

    return (
        {
            'product': None,
            'package': package,
            'item_name': package.name,
            'quantity': quantity,
            'unit_price': expected,
            'tax_type': package.tax_type,
            'customization': package_customization(package),
        },
        None,
    )
