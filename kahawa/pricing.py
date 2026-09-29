"""Shared storefront pricing rules (server + mirrored in kahawa-cart.js)."""

from decimal import Decimal

SIZE_EXTRAS = {
    'Regular': Decimal('0'),
    'Large': Decimal('50'),
}

MILK_EXTRAS = {
    'Dairy': Decimal('0'),
    'Oat': Decimal('50'),
    'Almond': Decimal('50'),
}

EXTRA_SHOT_FEE = Decimal('100')
DELIVERY_FEE = Decimal('100')


def customization_extras(customization: dict | None) -> Decimal:
    """Sum addon fees from a customization dict. Missing keys add nothing."""
    data = customization or {}
    total = Decimal('0')
    if data.get('size'):
        total += SIZE_EXTRAS.get(str(data.get('size')), Decimal('0'))
    if data.get('milk'):
        total += MILK_EXTRAS.get(str(data.get('milk')), Decimal('0'))
    if data.get('extra_shot'):
        total += EXTRA_SHOT_FEE
    return total


def normalize_customization(product, raw) -> dict:
    """Keep only options this product allows. Drop drink defaults on food."""
    data = raw if isinstance(raw, dict) else {}
    out: dict = {}
    if getattr(product, 'allow_size', False):
        size = str(data.get('size') or 'Regular')
        if size not in SIZE_EXTRAS:
            size = 'Regular'
        out['size'] = size
    if getattr(product, 'allow_milk', False):
        milk = str(data.get('milk') or 'Dairy')
        if milk not in MILK_EXTRAS:
            milk = 'Dairy'
        out['milk'] = milk
    if getattr(product, 'allow_extra_shot', False):
        out['extra_shot'] = bool(data.get('extra_shot'))
    return out


def unit_price_for_product(base_price: Decimal, customization: dict | None) -> Decimal:
    return Decimal(base_price) + customization_extras(customization)


def order_totals(
    subtotal: Decimal,
    order_type: str,
    discount: Decimal | int | float = 0,
    tax: Decimal | int | float = 0,
) -> dict[str, Decimal]:
    """
    Return subtotal, tax, delivery_fee, discount, and grand total.

    Tax is the VAT already inside the prices. It is not added again.
    """
    subtotal = Decimal(subtotal)
    tax = Decimal(str(tax or 0)).quantize(Decimal('0.01'))
    delivery = DELIVERY_FEE if order_type == 'DELIVERY' else Decimal('0')
    discount = Decimal(str(discount or 0)).quantize(Decimal('0.01'))
    if discount < 0:
        discount = Decimal('0')
    gross = subtotal + delivery
    if discount > gross:
        discount = gross
    total = gross - discount
    return {
        'subtotal': subtotal,
        'tax': tax,
        'delivery_fee': delivery,
        'discount': discount,
        'total': total,
    }
