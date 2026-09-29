"""Customer receipt context. Prices already include VAT."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .models import Order
from .pricing import DELIVERY_FEE


def _ksh(amount) -> str:
    value = Decimal(amount or 0)
    if value == value.to_integral():
        return f'{int(value):,}'
    return f'{value:,.2f}'


def _item_notes(item) -> tuple[list[str], list[str]]:
    custom = item.customization or {}
    notes = []
    if custom.get('size'):
        notes.append(str(custom['size']))
    if custom.get('milk'):
        notes.append(f"{custom['milk']} milk")
    if custom.get('extra_shot'):
        notes.append('Extra shot')
    components = []
    for part in custom.get('components') or []:
        name = part.get('name') or 'Item'
        qty = part.get('quantity') or 1
        components.append(f'{qty}× {name}')
    return notes, components


def receipt_context(order: Order, *, autoprint: bool = False) -> dict:
    items = list(order.items.all())
    subtotal = sum((item.line_total for item in items), Decimal('0'))
    discount = Decimal(order.discount_amount or 0)
    delivery = DELIVERY_FEE if order.order_type == Order.OrderType.DELIVERY else Decimal('0')
    total = Decimal(order.total_amount or 0)
    expected = subtotal + delivery - discount
    show_delivery = delivery > 0 and abs(expected - total) <= Decimal('1')

    served_by = ''
    if order.created_by_id and order.created_by:
        served_by = (order.created_by.get_full_name() or '').strip() or order.created_by.get_username()

    rows = []
    for item in items:
        notes, components = _item_notes(item)
        rows.append(
            {
                'quantity': item.quantity,
                'name': item.display_name,
                'notes': ' · '.join(notes),
                'components': components,
                'line_total': _ksh(item.line_total),
            }
        )

    when = timezone.localtime(order.paid_at or order.created_at)
    return {
        'order': order,
        'rows': rows,
        'cafe_name': settings.CAFE_NAME,
        'cafe_address': settings.CAFE_ADDRESS,
        'cafe_phone': settings.CAFE_PHONE,
        'subtotal': _ksh(subtotal),
        'discount': _ksh(discount),
        'show_discount': discount > 0,
        'delivery_fee': _ksh(delivery),
        'show_delivery': show_delivery,
        'tax_amount': _ksh(order.tax_amount or 0),
        'show_tax': Decimal(order.tax_amount or 0) > 0,
        'total': _ksh(total),
        'served_by': served_by,
        'cash_tendered': _ksh(order.cash_tendered) if order.cash_tendered is not None else '',
        'cash_change': _ksh(order.cash_change) if order.cash_change is not None else '',
        'show_cash': order.cash_tendered is not None,
        'when_display': when.strftime('%d %b %Y · %H:%M'),
        'autoprint': autoprint,
        'is_cancelled': order.status == Order.Status.CANCELLED,
        'is_paid': order.payment_status == Order.PaymentStatus.PAID,
    }


def kitchen_context(order: Order, *, autoprint: bool = False) -> dict:
    """Ticket for the pass. Items and notes only — no prices."""
    rows = []
    for item in order.items.select_related('product'):
        notes, components = _item_notes(item)
        if item.product_id and item.product and item.product.allergens:
            notes.append(f'Contains {item.product.allergens}')
        rows.append(
            {
                'quantity': item.quantity,
                'name': item.display_name,
                'notes': ' · '.join(notes),
                'components': components,
            }
        )
    when = timezone.localtime(order.created_at)
    return {
        'order': order,
        'rows': rows,
        'cafe_name': settings.CAFE_NAME,
        'when_display': when.strftime('%d %b %Y · %H:%M'),
        'autoprint': autoprint,
        'is_cancelled': order.status == Order.Status.CANCELLED,
    }
