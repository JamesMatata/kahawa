"""KRA eTIMS tax codes. Listed prices already include VAT."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# taxTyCd values used by KRA eTIMS.
TAX_TYPES = (
    ('A', 'A · Exempt', Decimal('0')),
    ('B', 'B · VAT 16%', Decimal('16')),
    ('C', 'C · Zero rated', Decimal('0')),
    ('D', 'D · Non-VAT', Decimal('0')),
    ('E', 'E · VAT 8%', Decimal('8')),
)
TAX_TYPE_CHOICES = [(code, label) for code, label, _rate in TAX_TYPES]
TAX_RATES = {code: rate for code, _label, rate in TAX_TYPES}
DEFAULT_TAX_TYPE = 'B'
DELIVERY_TAX_TYPE = 'B'
CENT = Decimal('0.01')


def normalize_tax_type(code) -> str:
    value = str(code or '').strip().upper()
    if value in TAX_RATES:
        return value
    return DEFAULT_TAX_TYPE


def tax_label(code) -> str:
    value = normalize_tax_type(code)
    for item_code, label, _rate in TAX_TYPES:
        if item_code == value:
            return label
    return value


def included_vat(amount, code) -> Decimal:
    """VAT already inside an inclusive amount. Zero-rate codes return 0."""
    amount = Decimal(amount or 0)
    if amount <= 0:
        return Decimal('0.00')
    rate = TAX_RATES[normalize_tax_type(code)]
    if rate <= 0:
        return Decimal('0.00')
    return (amount * rate / (Decimal('100') + rate)).quantize(CENT, rounding=ROUND_HALF_UP)


def order_included_tax(parts, discount=0) -> Decimal:
    """
    Sum included VAT after spreading a discount across parts.

    parts: sequence of (inclusive_amount, tax_code).
    """
    cleaned = []
    for amount, code in parts:
        amount = Decimal(amount or 0)
        if amount > 0:
            cleaned.append((amount, normalize_tax_type(code)))
    base = sum((amount for amount, _code in cleaned), Decimal('0'))
    discount = Decimal(str(discount or 0))
    if discount < 0:
        discount = Decimal('0')
    if discount > base:
        discount = base
    if not cleaned or base <= 0:
        return Decimal('0.00')

    tax = Decimal('0.00')
    remaining = discount
    for index, (amount, code) in enumerate(cleaned):
        if index == len(cleaned) - 1:
            share = remaining
        else:
            share = (discount * amount / base).quantize(CENT)
            remaining -= share
        net = amount - share
        if net < 0:
            net = Decimal('0')
        tax += included_vat(net, code)
    return tax.quantize(CENT)


def totals_for_lines(line_payloads, order_type: str, discount=0) -> dict:
    """Order totals. Tax is reported, and it is not added on top of the price."""
    from .pricing import DELIVERY_FEE, order_totals

    subtotal = sum(
        (
            Decimal(line['unit_price']) * int(line['quantity'])
            for line in line_payloads
        ),
        Decimal('0'),
    )
    parts = [
        (
            Decimal(line['unit_price']) * int(line['quantity']),
            line.get('tax_type') or DEFAULT_TAX_TYPE,
        )
        for line in line_payloads
    ]
    if order_type == 'DELIVERY':
        parts.append((DELIVERY_FEE, DELIVERY_TAX_TYPE))
    totals = order_totals(subtotal, order_type, discount=discount)
    totals['tax'] = order_included_tax(parts, discount)
    return totals
