"""Loyalty points helpers for Kahawa."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings

# 1 point per KSh 10 paid; 20 points = KSh 10 off
POINTS_PER_KSH = Decimal(getattr(settings, 'LOYALTY_POINTS_PER_KSH', '0.1'))  # 1 per 10
REDEEM_POINTS_PER_KSH = int(getattr(settings, 'LOYALTY_REDEEM_POINTS_PER_KSH', 2))  # 20 pts = 10 KSh → 2 pts/KSh
MAX_REDEEM_FRACTION = Decimal('0.5')


def points_for_amount(amount: Decimal | int | float) -> int:
    paid = Decimal(str(amount))
    if paid <= 0:
        return 0
    return int(paid * POINTS_PER_KSH)


def max_redeemable_points(balance: int, subtotal: Decimal) -> int:
    if balance <= 0 or subtotal <= 0:
        return 0
    max_discount = (subtotal * MAX_REDEEM_FRACTION).quantize(Decimal('1'))
    max_by_value = int(max_discount * REDEEM_POINTS_PER_KSH)
    # Round down to multiples of redeem rate for clean KSh
    usable = min(balance, max_by_value)
    if REDEEM_POINTS_PER_KSH > 1:
        usable = (usable // REDEEM_POINTS_PER_KSH) * REDEEM_POINTS_PER_KSH
    return max(0, usable)


def discount_for_points(points: int) -> Decimal:
    if points <= 0 or REDEEM_POINTS_PER_KSH <= 0:
        return Decimal('0')
    return Decimal(points // REDEEM_POINTS_PER_KSH)


def apply_order_paid_loyalty(order) -> None:
    """Award points after successful payment (idempotent via points_earned)."""
    from .models import CustomerProfile

    if order.points_earned:
        return
    if not order.user_id:
        return

    earned = points_for_amount(order.total_amount)
    if earned <= 0:
        return

    profile, _ = CustomerProfile.objects.get_or_create(user=order.user)
    profile.loyalty_points = (profile.loyalty_points or 0) + earned
    profile.save(update_fields=['loyalty_points'])
    order.points_earned = earned
    order.save(update_fields=['points_earned'])


def restore_order_discounts(order) -> None:
    """Return redeemed points / gift balance if payment failed after checkout."""
    from .models import CustomerProfile, GiftCard
    from .tax import totals_for_lines

    if order.payment_status == order.PaymentStatus.PAID:
        return
    if not order.points_redeemed and not order.gift_card_amount and not order.discount_amount:
        return

    if order.user_id and order.points_redeemed:
        profile, _ = CustomerProfile.objects.get_or_create(user=order.user)
        profile.loyalty_points = (profile.loyalty_points or 0) + order.points_redeemed
        profile.save(update_fields=['loyalty_points'])
        order.points_redeemed = 0

    if order.gift_card_id and order.gift_card_amount:
        gift = GiftCard.objects.filter(pk=order.gift_card_id).first()
        if gift:
            gift.balance = (gift.balance + order.gift_card_amount).quantize(
                Decimal('0.01')
            )
            gift.save(update_fields=['balance'])
        order.gift_card_amount = Decimal('0')
        order.gift_card = None

    if order.discount_amount:
        order.discount_amount = Decimal('0')

    # Rebuild undiscounted total so a retry STK charges the correct amount.
    payloads = [
        {
            'unit_price': item.unit_price,
            'quantity': item.quantity,
            'tax_type': item.tax_type,
        }
        for item in order.items.all()
    ]
    totals = totals_for_lines(payloads, order.order_type, discount=Decimal('0'))
    order.tax_amount = totals['tax']
    order.total_amount = totals['total']

    order.save(
        update_fields=[
            'points_redeemed',
            'gift_card',
            'gift_card_amount',
            'discount_amount',
            'tax_amount',
            'total_amount',
        ]
    )


def fail_and_cancel_unpaid_order(
    order, *, reason: str = 'Payment failed or timed out'
) -> None:
    """Mark payment failed, restore discounts, and pull the order off Live ops."""
    from django.utils import timezone

    if order.payment_status == order.PaymentStatus.PAID:
        return

    order.payment_status = order.PaymentStatus.FAILED
    order.save(update_fields=['payment_status'])
    restore_order_discounts(order)

    if order.status != order.Status.CANCELLED:
        order.status = order.Status.CANCELLED
        order.cancelled_at = timezone.now()
        order.cancel_reason = (reason or '')[:200]
        order.save(
            update_fields=['status', 'cancelled_at', 'cancel_reason', 'updated_at']
        )