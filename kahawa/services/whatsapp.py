"""WhatsApp receipt helpers — preferred channel for Kahawa (phone-first Kenya)."""

from __future__ import annotations

from urllib.parse import quote

from django.conf import settings
from django.urls import reverse


def build_receipt_text(order) -> str:
    site = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
    detail = f"{site}{reverse('kahawa:order_detail', kwargs={'order_code': order.order_code})}"
    lines = [
        f"Kahawa receipt · {order.order_code}",
        f"{order.customer_name}",
        f"Total: KSh {int(order.total_amount):,}",
        f"Status: {order.get_payment_status_display()} · {order.get_order_type_display()}",
    ]
    if order.table_id:
        lines.append(f"Table: {order.table.code}")
    if getattr(order, 'mpesa_receipt', ''):
        lines.append(f"M-Pesa: {order.mpesa_receipt}")
    lines.append(f"View: {detail}")
    return '\n'.join(lines)


def whatsapp_receipt_url(order, phone: str | None = None) -> str:
    """
    Deep-link to WhatsApp with a prefilled receipt.
    Uses order phone (or cafe WhatsApp as chat target if sending to self share).
    For customer share-to-self, leave phone empty so WhatsApp opens contact picker;
    for send-to-customer number, pass digits.
    """
    text = build_receipt_text(order)
    target = ''
    if phone:
        digits = ''.join(c for c in phone if c.isdigit())
        if digits.startswith('0') and len(digits) >= 10:
            digits = f'254{digits[1:10]}'
        elif digits.startswith('254'):
            pass
        target = digits
    if target:
        return f'https://wa.me/{target}?text={quote(text)}'
    return f'https://wa.me/?text={quote(text)}'
