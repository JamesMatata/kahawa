import json
import random
import re
import time
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import Category, CustomerProfile, Order, OrderItem, Product
from .pricing import normalize_customization, unit_price_for_product
from .ratelimit import rate_limit
from .services.sms import format_kenyan_phone, send_order_confirmation_sms

MOCK_PAYMENT_WAIT_SECONDS = 5

KENYAN_PHONE_RE = re.compile(r'^(?:0[17]\d{8}|\+?254[17]\d{8})$')

TRACK_STEPS = (
    ('PENDING', 'Received'),
    ('PREPARING', 'Preparing'),
    ('READY', 'Ready'),
    ('COMPLETED', 'Completed'),
)


class _OrderCreateError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status
        super().__init__(message)


def _phones_match(stored: str, provided: str) -> bool:
    try:
        return format_kenyan_phone(stored) == format_kenyan_phone(provided)
    except Exception:
        return False


def _order_stepper_context(order: Order) -> dict:
    """Build visual stepper state for an order status card."""
    status = order.status
    cancelled = status == Order.Status.CANCELLED

    ready_label = (
        'Out for Delivery'
        if order.order_type == Order.OrderType.DELIVERY
        else 'Ready at table'
        if order.order_type == Order.OrderType.DINE_IN
        else 'Ready for Pickup'
    )
    steps = [
        {'key': 'PENDING', 'label': 'Received'},
        {'key': 'PREPARING', 'label': 'Preparing'},
        {'key': 'READY', 'label': ready_label},
        {'key': 'COMPLETED', 'label': 'Completed'},
    ]

    active_index = -1
    if not cancelled:
        for i, (key, _) in enumerate(TRACK_STEPS):
            if status == key:
                active_index = i
                break
        else:
            active_index = 0

    return {
        'steps': steps,
        'active_index': active_index,
        'cancelled': cancelled,
    }


def home(request):
    featured_categories = Category.objects.filter(is_featured=True)
    featured_products = (
        Product.objects.filter(is_featured=True, is_available=True)
        .select_related('category')
        .order_by('name')
    )
    from .offers import live_packages

    return render(
        request,
        'store/home.html',
        {
            'featured_categories': featured_categories,
            'featured_products': featured_products,
            'packages': live_packages(),
        },
    )


def product_list(request):
    categories = (
        Category.objects.filter(products__isnull=False)
        .distinct()
        .order_by('name')
    )
    products = (
        Product.objects.filter(is_available=True)
        .select_related('category')
        .order_by('category__name', 'name')
    )
    sold_out_products = (
        Product.objects.filter(is_available=False)
        .select_related('category')
        .order_by('category__name', 'name')
    )
    table_code = (request.session.get('table_code') or '').strip()
    table_label = ''
    if table_code:
        from .models import CafeTable

        table = CafeTable.objects.filter(code__iexact=table_code, is_active=True).first()
        if table:
            table_label = table.label
        else:
            table_code = ''
            request.session.pop('table_code', None)

    from .offers import live_packages

    return render(
        request,
        'store/menu.html',
        {
            'categories': categories,
            'products': products,
            'sold_out_products': sold_out_products,
            'packages': live_packages(),
            'table_code': table_code,
            'table_label': table_label,
        },
    )


@rate_limit(key='track', limit=20, window=60)
@require_http_methods(['GET', 'POST'])
def track_order(request):
    """
    Public tracker: order code + phone lookup.
    Prefills code from ?code= (e.g. SMS / confirmation links).
    """
    order = None
    error = ''
    order_code = (request.GET.get('code') or '').strip().upper()
    phone = ''

    if request.method == 'POST':
        order_code = (request.POST.get('order_code') or '').strip().upper()
        phone = (request.POST.get('phone') or '').strip()

        if not order_code or not phone:
            error = 'Enter both your order code and phone number.'
        else:
            candidate = (
                Order.objects.filter(order_code__iexact=order_code)
                .prefetch_related('items__product')
                .first()
            )
            if not candidate or not _phones_match(candidate.phone, phone):
                error = 'We couldn’t find an order with that code and phone number.'
            else:
                order = candidate

    context = {
        'order': order,
        'error': error,
        'order_code': order_code,
        'phone': phone,
    }
    if order:
        context.update(_order_stepper_context(order))

    return render(request, 'store/track_order.html', context)


@require_GET
def orders(request):
    """
    Orders hub: account orders when logged in; guests load device orders via JS.
    """
    account_orders = []
    if request.user.is_authenticated:
        account_orders = list(
            Order.objects.filter(user=request.user)
            .prefetch_related('items__product')
            .order_by('-created_at')
        )
    return render(
        request,
        'store/orders.html',
        {
            'account_orders': account_orders,
            'is_authenticated': request.user.is_authenticated,
        },
    )


@require_POST
def orders_by_codes(request):
    """Return order summaries for guest device codes (JSON)."""
    payload = _parse_json_body(request)
    if payload is None:
        return JsonResponse({'ok': False, 'error': 'Invalid request.'}, status=400)

    raw_codes = payload.get('codes') or []
    if not isinstance(raw_codes, list):
        return JsonResponse({'ok': False, 'error': 'Invalid codes.'}, status=400)

    codes = []
    for code in raw_codes[:20]:
        cleaned = str(code or '').strip().upper()
        if cleaned and cleaned not in codes:
            codes.append(cleaned)

    if not codes:
        return JsonResponse({'ok': True, 'orders': []})

    qs = (
        Order.objects.filter(order_code__in=codes)
        .prefetch_related('items__product')
        .order_by('-created_at')
    )
    # Preserve device list order where possible
    by_code = {o.order_code.upper(): o for o in qs}
    orders_out = []
    for code in codes:
        order = by_code.get(code)
        if not order:
            continue
        orders_out.append(_order_summary_dict(order))

    return JsonResponse({'ok': True, 'orders': orders_out})


def _order_summary_dict(order: Order) -> dict:
    item_count = order.items.count()
    return {
        'code': order.order_code,
        'status': order.status,
        'status_label': order.get_status_display(),
        'payment_status': order.payment_status,
        'payment_label': order.get_payment_status_display(),
        'order_type': order.order_type,
        'order_type_label': order.get_order_type_display(),
        'total': int(order.total_amount),
        'item_count': item_count,
        'created_at': order.created_at.strftime('%a, %b %-d · %-I:%M %p')
        if False
        else order.created_at.strftime('%a, %b %d · %I:%M %p'),
        'url': reverse('kahawa:order_detail', kwargs={'order_code': order.order_code}),
    }


@require_GET
def order_receipt(request, order_code):
    """Printable customer slip. Reprint by opening the same link."""
    from .receipts import receipt_context

    order = get_object_or_404(
        Order.objects.select_related('table', 'created_by').prefetch_related('items'),
        order_code__iexact=order_code,
    )
    return render(
        request,
        'store/receipt.html',
        receipt_context(order, autoprint=request.GET.get('print') == '1'),
    )


@require_GET
def order_detail(request, order_code):
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product'),
        order_code__iexact=order_code,
    )

    allowed = False
    if request.user.is_authenticated and order.user_id == request.user.id:
        allowed = True
    elif request.user.is_authenticated and request.user.is_staff:
        allowed = True
    else:
        # Guests may open orders whose codes they hold (device history / confirmation).
        allowed = True

    if not allowed:
        return redirect('kahawa:orders')

    context = {
        'order': order,
        'is_owner': request.user.is_authenticated and order.user_id == request.user.id,
        'reorder_items': [
            i for i in _reorder_items_payload(order) if i.get('available')
        ],
    }
    context.update(_order_stepper_context(order))
    return render(request, 'store/order_detail.html', context)


@login_required(login_url='/accounts/login/')
@require_GET
def my_orders(request):
    return redirect('kahawa:orders')


def _checkout_prefill(request):
    user = request.user
    prefill = {
        'name': '',
        'phone': '',
        'email': '',
        'location': '',
    }
    if user.is_authenticated:
        full_name = user.get_full_name().strip()
        prefill['name'] = full_name or user.username
        prefill['email'] = user.email or ''
        profile = getattr(user, 'profile', None)
        if profile is None:
            try:
                profile = CustomerProfile.objects.get(user=user)
            except CustomerProfile.DoesNotExist:
                profile = None
        if profile:
            prefill['phone'] = profile.phone or ''
            prefill['location'] = profile.default_location or ''
    return prefill


@require_GET
def cart(request):
    loyalty_points = 0
    if request.user.is_authenticated:
        profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
        loyalty_points = profile.loyalty_points or 0

    table_code = (request.session.get('table_code') or '').strip()
    table_label = ''
    if table_code:
        from .models import CafeTable

        table = CafeTable.objects.filter(code__iexact=table_code, is_active=True).first()
        if table:
            table_label = table.label
        else:
            table_code = ''
            request.session.pop('table_code', None)

    return render(
        request,
        'store/cart.html',
        {
            'prefill': _checkout_prefill(request),
            'is_authenticated': request.user.is_authenticated,
            'loyalty_points': loyalty_points,
            'table_code': table_code,
            'table_label': table_label,
        },
    )


@require_GET
def checkout(request):
    return redirect('kahawa:cart')


def _parse_json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _validate_kenyan_phone(phone: str) -> str | None:
    cleaned = (phone or '').strip().replace(' ', '')
    if not KENYAN_PHONE_RE.match(cleaned):
        return None
    return format_kenyan_phone(cleaned)


def _payload_from_request(request):
    payload = _parse_json_body(request)
    if payload is not None:
        return payload
    try:
        cart_raw = request.POST.get('cart', '[]')
        cart_items = json.loads(cart_raw)
    except json.JSONDecodeError:
        return None
    return {
        'cart': cart_items,
        'customer_name': request.POST.get('customer_name', ''),
        'phone': request.POST.get('phone', ''),
        'email': request.POST.get('email', ''),
        'order_type': request.POST.get('order_type', 'PICKUP'),
        'delivery_location': request.POST.get('delivery_location', ''),
        'delivery_confirmed': request.POST.get('delivery_confirmed') in (
            '1',
            'true',
            'on',
            True,
        ),
    }


def _create_order_from_payload(request, payload, *, prep_after_payment: bool = False):
    """
    Validate payload and create Order + items.
    Returns (order, email, None) on success or (None, None, JsonResponse) on error.
    """
    cart_items = payload.get('cart') or []
    if not isinstance(cart_items, list) or not cart_items:
        return None, None, JsonResponse({'ok': False, 'error': 'Your bag is empty.'}, status=400)

    customer_name = (payload.get('customer_name') or '').strip()
    phone_raw = (payload.get('phone') or '').strip()
    email = (payload.get('email') or '').strip()
    order_type = (payload.get('order_type') or 'PICKUP').upper()
    delivery_location = (payload.get('delivery_location') or '').strip()
    delivery_confirmed = bool(payload.get('delivery_confirmed'))

    if not customer_name:
        return None, None, JsonResponse(
            {'ok': False, 'error': 'Please enter your name.'}, status=400
        )

    phone = ''
    if phone_raw:
        phone = _validate_kenyan_phone(phone_raw)
        if not phone:
            return None, None, JsonResponse(
                {
                    'ok': False,
                    'error': 'Enter a valid Kenyan phone number (07… or 01…), or leave it blank.',
                },
                status=400,
            )

    if order_type not in (
        Order.OrderType.PICKUP,
        Order.OrderType.DELIVERY,
        Order.OrderType.DINE_IN,
    ):
        return None, None, JsonResponse(
            {'ok': False, 'error': 'Invalid order type.'}, status=400
        )

    table = None
    table_code = (payload.get('table_code') or request.session.get('table_code') or '').strip()
    if order_type == Order.OrderType.DINE_IN or table_code:
        from .models import CafeTable

        if not table_code:
            return None, None, JsonResponse(
                {'ok': False, 'error': 'Select a table or scan a table QR to dine in.'},
                status=400,
            )
        table = CafeTable.objects.filter(code__iexact=table_code, is_active=True).first()
        if not table:
            return None, None, JsonResponse(
                {'ok': False, 'error': 'This table is not available.'}, status=400
            )
        order_type = Order.OrderType.DINE_IN
        delivery_location = ''
    elif order_type == Order.OrderType.DELIVERY:
        if not delivery_location:
            return None, None, JsonResponse(
                {
                    'ok': False,
                    'error': 'Please enter your delivery address / building name.',
                },
                status=400,
            )
        if not delivery_confirmed:
            return None, None, JsonResponse(
                {
                    'ok': False,
                    'error': 'Please confirm your delivery location is within 1 km.',
                },
                status=400,
            )
    else:
        delivery_location = ''

    line_payloads = []
    subtotal = Decimal('0.00')

    for raw in cart_items:
        if raw.get('packageId') or raw.get('package_id'):
            from .offers import resolve_package_line

            line, error = resolve_package_line(raw)
            if error:
                return None, None, error
            line_payloads.append(line)
            subtotal += line['unit_price'] * line['quantity']
            continue
        try:
            product_id = int(raw.get('productId') or raw.get('product_id'))
            quantity = int(raw.get('quantity') or 0)
        except (TypeError, ValueError):
            return None, None, JsonResponse(
                {'ok': False, 'error': 'Invalid cart item.'}, status=400
            )

        if quantity < 1:
            return None, None, JsonResponse(
                {'ok': False, 'error': 'Invalid item quantity.'}, status=400
            )

        try:
            product = Product.objects.get(pk=product_id, is_available=True)
        except Product.DoesNotExist:
            return None, None, JsonResponse(
                {'ok': False, 'error': 'One of your items is no longer available.'},
                status=400,
            )

        customization = normalize_customization(product, raw.get('customization'))
        expected_unit = unit_price_for_product(product.price, customization)

        client_unit = raw.get('unitPrice', raw.get('unit_price'))
        if client_unit is not None:
            try:
                client_decimal = Decimal(str(client_unit)).quantize(Decimal('0.01'))
            except (InvalidOperation, TypeError, ValueError):
                return None, None, JsonResponse(
                    {'ok': False, 'error': 'Invalid item price.'}, status=400
                )
            if client_decimal != expected_unit.quantize(Decimal('0.01')):
                return None, None, JsonResponse(
                    {
                        'ok': False,
                        'error': (
                            f'Price mismatch for {product.name}. '
                            'Please refresh your bag and try again.'
                        ),
                    },
                    status=400,
                )

        line_payloads.append(
            {
                'product': product,
                'quantity': quantity,
                'unit_price': expected_unit,
                'tax_type': product.tax_type,
                'customization': customization,
            }
        )
        subtotal += expected_unit * quantity

    # Discounts: loyalty points + gift card
    from .loyalty import discount_for_points, max_redeemable_points
    from .models import GiftCard

    points_to_redeem = 0
    points_discount = Decimal('0')
    if request.user.is_authenticated and payload.get('redeem_points'):
        try:
            points_to_redeem = int(payload.get('redeem_points') or 0)
        except (TypeError, ValueError):
            points_to_redeem = 0
        profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
        max_pts = max_redeemable_points(profile.loyalty_points or 0, subtotal)
        points_to_redeem = max(0, min(points_to_redeem, max_pts))
        points_discount = discount_for_points(points_to_redeem)

    gift_code = (payload.get('gift_card_code') or '').strip().upper()
    gift_card = None
    gift_amount = Decimal('0')

    from .tax import totals_for_lines

    tentative = totals_for_lines(line_payloads, order_type, discount=points_discount)
    remaining_after_points = tentative['total']

    try:
        with transaction.atomic():
            if gift_code:
                gift_card = (
                    GiftCard.objects.select_for_update()
                    .filter(code__iexact=gift_code, is_active=True, payment_status='PAID')
                    .first()
                )
                if not gift_card or gift_card.balance <= 0:
                    raise _OrderCreateError('Gift card not found or has no balance.')
                gift_amount = min(Decimal(gift_card.balance), remaining_after_points)

            totals = totals_for_lines(
                line_payloads,
                order_type,
                discount=points_discount + gift_amount,
            )

            if request.user.is_authenticated and points_to_redeem:
                profile, _ = CustomerProfile.objects.select_for_update().get_or_create(
                    user=request.user
                )
                if (profile.loyalty_points or 0) < points_to_redeem:
                    raise _OrderCreateError('Not enough loyalty points.')
                profile.loyalty_points -= points_to_redeem
                profile.save(update_fields=['loyalty_points'])

            if gift_card and gift_amount > 0:
                gift_card.balance = (gift_card.balance - gift_amount).quantize(
                    Decimal('0.01')
                )
                gift_card.save(update_fields=['balance'])

            order = Order(
                customer_name=customer_name,
                phone=phone,
                order_type=order_type,
                delivery_location=delivery_location,
                table=table,
                source=Order.Source.STOREFRONT,
                discount_amount=points_discount + gift_amount,
                points_redeemed=points_to_redeem,
                gift_card=gift_card,
                gift_card_amount=gift_amount,
                tax_amount=totals['tax'],
                total_amount=totals['total'],
                status=Order.Status.PENDING,
                payment_status=Order.PaymentStatus.PENDING,
                prep_after_payment=prep_after_payment,
            )
            if request.user.is_authenticated:
                order.user = request.user
            order.save()

            OrderItem.objects.bulk_create(
                [
                    OrderItem(
                        order=order,
                        product=line['product'],
                        package=line.get('package'),
                        item_name=line.get('item_name') or '',
                        tax_type=line.get('tax_type') or 'B',
                        quantity=line['quantity'],
                        unit_price=line['unit_price'],
                        customization=line['customization'],
                    )
                    for line in line_payloads
                ]
            )

            if (
                request.user.is_authenticated
                and bool(payload.get('save_location'))
                and order_type == Order.OrderType.DELIVERY
                and delivery_location
            ):
                profile, _ = CustomerProfile.objects.get_or_create(user=request.user)
                if delivery_location != profile.default_location:
                    profile.default_location = delivery_location
                    profile.save(update_fields=['default_location'])
    except _OrderCreateError as exc:
        return None, None, JsonResponse(
            {'ok': False, 'error': exc.message},
            status=exc.status,
        )
    except Exception:
        return None, None, JsonResponse(
            {'ok': False, 'error': 'Could not place your order. Please try again.'},
            status=500,
        )

    return order, email, None


def _start_stk(order: Order, phone: str | None = None) -> dict:
    """Initiate STK (live or mock) and persist checkout id on the order."""
    from .services import mpesa as mpesa_service

    pay_phone = phone or order.phone
    result = mpesa_service.initiate_stk_push(order=order, phone=pay_phone)
    if not result.get('ok'):
        return result

    checkout_id = result['checkout_request_id']
    order.mpesa_checkout_request_id = checkout_id
    order.payment_status = Order.PaymentStatus.PENDING
    order.payment_method = Order.PaymentMethod.MPESA
    order.mpesa_receipt = ''
    order.save(
        update_fields=[
            'mpesa_checkout_request_id',
            'payment_status',
            'payment_method',
            'mpesa_receipt',
        ]
    )

    cache.set(f'kahawa_pay_start:{order.order_code}', time.time(), timeout=600)
    cache.delete(f'kahawa_pay_outcome:{order.order_code}')

    if result.get('mock'):
        # Demo path — outcome resolved on poll after wait.
        pass

    return result


def _resolve_mock_payment(order: Order) -> str:
    """Advance PENDING mock payment after wait; returns current status value."""
    from django.conf import settings as dj_settings

    from .loyalty import fail_and_cancel_unpaid_order, restore_order_discounts
    from .services import mpesa as mpesa_service

    if order.payment_status != Order.PaymentStatus.PENDING:
        return order.payment_status

    started = cache.get(f'kahawa_pay_start:{order.order_code}')
    if started is None:
        return Order.PaymentStatus.PENDING

    elapsed = time.time() - float(started)
    timeout = getattr(dj_settings, 'PAYMENT_TIMEOUT_SECONDS', 90)

    def _fail():
        if order.prep_after_payment:
            fail_and_cancel_unpaid_order(order)
        else:
            order.payment_status = Order.PaymentStatus.FAILED
            order.save(update_fields=['payment_status'])
            restore_order_discounts(order)
        return Order.PaymentStatus.FAILED

    # Live payments: only timeout; success comes from callback.
    if mpesa_service.is_live() and not str(order.mpesa_checkout_request_id or '').startswith(
        'ws_'
    ):
        if elapsed >= timeout:
            return _fail()
        return Order.PaymentStatus.PENDING

    if elapsed < MOCK_PAYMENT_WAIT_SECONDS:
        return Order.PaymentStatus.PENDING

    if elapsed >= timeout:
        cache.set(
            f'kahawa_pay_outcome:{order.order_code}',
            Order.PaymentStatus.FAILED,
            timeout=600,
        )
        return _fail()

    outcome = cache.get(f'kahawa_pay_outcome:{order.order_code}')
    if outcome is None:
        outcome = (
            Order.PaymentStatus.PAID
            if random.random() < 0.75
            else Order.PaymentStatus.FAILED
        )
        cache.set(f'kahawa_pay_outcome:{order.order_code}', outcome, timeout=600)
        if outcome == Order.PaymentStatus.PAID:
            from django.utils import timezone as dj_tz

            from .loyalty import apply_order_paid_loyalty

            order.payment_status = Order.PaymentStatus.PAID
            order.paid_at = dj_tz.now()
            order.payment_method = Order.PaymentMethod.MPESA
            if not order.mpesa_receipt:
                order.mpesa_receipt = f'MOCK{uuid.uuid4().hex[:8].upper()}'
            order.save(
                update_fields=[
                    'payment_status',
                    'paid_at',
                    'payment_method',
                    'mpesa_receipt',
                ]
            )
            apply_order_paid_loyalty(order)
            send_order_confirmation_sms(order)
        else:
            return _fail()

    return order.payment_status


def _confirmation_url(order: Order) -> str:
    return reverse('kahawa:order_confirmation', kwargs={'order_code': order.order_code})


@rate_limit(key='place_order', limit=15, window=60)
@require_POST
def place_order(request):
    """
    Create an unpaid order (pay later). Storefront: dine-in / table only.
    Prefer start_payment for the STK / pay-modal flow.
    """
    payload = _payload_from_request(request)
    if payload is None:
        return JsonResponse({'ok': False, 'error': 'Invalid cart data.'}, status=400)

    # Pay later is only for dine-in (scanned table) — not pickup/delivery.
    order_type = (payload.get('order_type') or Order.OrderType.PICKUP).upper()
    table_code = (payload.get('table_code') or request.session.get('table_code') or '').strip()
    if order_type != Order.OrderType.DINE_IN and not table_code:
        return JsonResponse(
            {
                'ok': False,
                'error': 'Pay later is only available for dine-in table orders. Please pay with M-Pesa.',
            },
            status=400,
        )

    order, email, error = _create_order_from_payload(
        request, payload, prep_after_payment=False
    )
    if error:
        return error

    request.session.pop('table_code', None)

    # Fully covered by gift/points — treat as paid so Live ops isn't stuck.
    if Decimal(order.total_amount) <= 0:
        from django.utils import timezone as dj_tz

        from .loyalty import apply_order_paid_loyalty

        order.payment_status = Order.PaymentStatus.PAID
        order.paid_at = dj_tz.now()
        order.save(update_fields=['payment_status', 'paid_at'])
        apply_order_paid_loyalty(order)

    send_order_confirmation_sms(order)
    confirmation_url = _confirmation_url(order)
    wants_json = (
        'application/json' in (request.headers.get('Accept') or '')
        or request.content_type == 'application/json'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )
    if wants_json:
        return JsonResponse(
            {
                'ok': True,
                'order_code': order.order_code,
                'redirect_url': confirmation_url,
                'is_guest': not request.user.is_authenticated,
                'email': email,
            }
        )
    return redirect(confirmation_url)


@rate_limit(key='start_payment', limit=15, window=60)
@require_POST
def start_payment(request):
    """
    Create order (or retry existing) and start M-Pesa STK prompt.
    Body: full checkout payload, or { order_code, phone } for retry.
    """
    payload = _parse_json_body(request)
    if payload is None:
        return JsonResponse({'ok': False, 'error': 'Invalid request.'}, status=400)

    order_code = (payload.get('order_code') or '').strip()

    if order_code:
        order = get_object_or_404(Order, order_code=order_code)
        if order.payment_status == Order.PaymentStatus.PAID:
            return JsonResponse(
                {
                    'ok': True,
                    'order_code': order.order_code,
                    'payment_status': Order.PaymentStatus.PAID,
                    'redirect_url': _confirmation_url(order),
                }
            )

        phone_raw = (payload.get('phone') or '').strip()
        phone = None
        if phone_raw:
            phone = _validate_kenyan_phone(phone_raw)
            if not phone:
                return JsonResponse(
                    {
                        'ok': False,
                        'error': 'Enter a valid Kenyan phone number (07… or 01…).',
                    },
                    status=400,
                )
            order.phone = phone
            order.save(update_fields=['phone'])

        result = _start_stk(order, phone=phone)
        if not result.get('ok'):
            return JsonResponse(
                {'ok': False, 'error': result.get('error') or 'Could not start payment.'},
                status=400,
            )
        return JsonResponse(
            {
                'ok': True,
                'order_code': order.order_code,
                'checkout_request_id': result.get('checkout_request_id'),
                'payment_status': Order.PaymentStatus.PENDING,
                'is_guest': not request.user.is_authenticated,
                'message': result.get('customer_message') or '',
                'timeout_seconds': settings.PAYMENT_TIMEOUT_SECONDS,
            }
        )

    order, email, error = _create_order_from_payload(
        request, payload, prep_after_payment=True
    )
    if error:
        return error

    request.session.pop('table_code', None)

    # Fully covered by points / gift card — no STK needed
    if Decimal(order.total_amount) <= 0:
        from django.utils import timezone as dj_tz

        from .loyalty import apply_order_paid_loyalty

        order.payment_status = Order.PaymentStatus.PAID
        order.prep_after_payment = False
        order.paid_at = dj_tz.now()
        if not order.payment_method:
            order.payment_method = Order.PaymentMethod.NONE
        order.save(
            update_fields=[
                'payment_status',
                'paid_at',
                'payment_method',
                'prep_after_payment',
            ]
        )
        apply_order_paid_loyalty(order)
        send_order_confirmation_sms(order)
        return JsonResponse(
            {
                'ok': True,
                'order_code': order.order_code,
                'payment_status': Order.PaymentStatus.PAID,
                'redirect_url': _confirmation_url(order),
                'is_guest': not request.user.is_authenticated,
                'email': email,
            }
        )

    pay_phone = order.phone
    if not pay_phone:
        from .loyalty import fail_and_cancel_unpaid_order

        fail_and_cancel_unpaid_order(order, reason='Missing M-Pesa phone')
        return JsonResponse(
            {
                'ok': False,
                'error': 'Enter an M-Pesa phone number to pay now.',
            },
            status=400,
        )

    result = _start_stk(order, phone=pay_phone)
    if not result.get('ok'):
        from .loyalty import fail_and_cancel_unpaid_order

        fail_and_cancel_unpaid_order(
            order, reason='Could not start M-Pesa payment'
        )
        return JsonResponse(
            {'ok': False, 'error': result.get('error') or 'Could not start payment.'},
            status=400,
        )
    return JsonResponse(
        {
            'ok': True,
            'order_code': order.order_code,
            'checkout_request_id': result.get('checkout_request_id'),
            'payment_status': Order.PaymentStatus.PENDING,
            'is_guest': not request.user.is_authenticated,
            'email': email,
            'message': result.get('customer_message') or '',
            'timeout_seconds': settings.PAYMENT_TIMEOUT_SECONDS,
        }
    )


@rate_limit(key='payment_status', limit=60, window=60, methods=('GET',))
@require_GET
def payment_status(request, order_code):
    order = get_object_or_404(Order, order_code=order_code)
    status = _resolve_mock_payment(order)
    order.refresh_from_db(fields=['payment_status', 'mpesa_receipt'])
    status = order.payment_status

    data = {
        'ok': True,
        'order_code': order.order_code,
        'payment_status': status,
        'timeout_seconds': settings.PAYMENT_TIMEOUT_SECONDS,
    }
    if status == Order.PaymentStatus.PAID:
        data['redirect_url'] = _confirmation_url(order)
        if order.mpesa_receipt:
            data['receipt'] = order.mpesa_receipt
    return JsonResponse(data)


def _handle_mpesa_callback(request, secret: str | None = None):
    """Daraja STK callback for orders and gift cards."""
    from django.utils import timezone as dj_tz

    from .loyalty import apply_order_paid_loyalty, fail_and_cancel_unpaid_order
    from .models import GiftCard
    from .services import mpesa as mpesa_service

    if not mpesa_service.verify_callback_secret(secret):
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Unauthorized'}, status=403)

    payload = _parse_json_body(request) or {}
    parsed = mpesa_service.parse_callback(payload)
    checkout_id = parsed.get('checkout_request_id') or ''
    if not checkout_id:
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Missing CheckoutRequestID'})

    ok, err = mpesa_service.verify_callback_checkout(
        checkout_id, amount=parsed.get('amount') if parsed.get('success') else None
    )
    if not ok:
        return JsonResponse({'ResultCode': 1, 'ResultDesc': err or 'Rejected'})

    mpesa_service.pop_pending_stk(checkout_id)

    order = Order.objects.filter(mpesa_checkout_request_id=checkout_id).first()
    gift = GiftCard.objects.filter(mpesa_checkout_request_id=checkout_id).first()

    if not order and not gift:
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    if parsed.get('success'):
        if order and order.payment_status != Order.PaymentStatus.PAID:
            order.payment_status = Order.PaymentStatus.PAID
            order.payment_method = Order.PaymentMethod.MPESA
            order.mpesa_receipt = parsed.get('receipt') or order.mpesa_receipt
            order.paid_at = dj_tz.now()
            order.save(
                update_fields=[
                    'payment_status',
                    'payment_method',
                    'mpesa_receipt',
                    'paid_at',
                ]
            )
            apply_order_paid_loyalty(order)
            send_order_confirmation_sms(order)
        if gift and gift.payment_status != 'PAID':
            _mark_gift_paid(gift, gift.PaymentMethod.MPESA)
    else:
        if order and order.payment_status != Order.PaymentStatus.PAID:
            if order.prep_after_payment:
                fail_and_cancel_unpaid_order(order)
            else:
                from .loyalty import restore_order_discounts

                order.payment_status = Order.PaymentStatus.FAILED
                order.save(update_fields=['payment_status'])
                restore_order_discounts(order)
        if gift and gift.payment_status != 'PAID':
            _mark_gift_unpaid(gift, failed=True)

    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@csrf_exempt
@require_http_methods(['POST'])
def mpesa_callback(request):
    """Open callback URL — only allowed when MPESA_CALLBACK_SECRET is unset."""
    return _handle_mpesa_callback(request, secret=None)


@csrf_exempt
@require_http_methods(['POST'])
def mpesa_callback_secure(request, secret):
    """Preferred callback URL with path secret."""
    return _handle_mpesa_callback(request, secret=secret)

@require_GET
def order_confirmation(request, order_code):
    from .services.whatsapp import whatsapp_receipt_url

    # Safety: don't keep dine-in session after guest lands on confirmation
    request.session.pop('table_code', None)

    order = get_object_or_404(
        Order.objects.select_related('table').prefetch_related('items__product'),
        order_code=order_code,
    )
    return render(
        request,
        'store/confirmation.html',
        {
            'order': order,
            'whatsapp_url': whatsapp_receipt_url(order, phone=order.phone),
            'whatsapp_share_url': whatsapp_receipt_url(order),
        },
    )


@require_GET
def table_entry(request, code):
    """Scan table QR → set session table and go to menu (dine-in)."""
    from .models import CafeTable

    table = CafeTable.objects.filter(code__iexact=code).first()
    if not table or not table.is_active:
        return render(
            request,
            'store/table_unavailable.html',
            {
                'code': (code or '').strip(),
                'inactive': bool(table and not table.is_active),
            },
            status=404,
        )
    request.session['table_code'] = table.code
    return redirect('kahawa:menu')


@require_POST
def clear_table(request):
    request.session.pop('table_code', None)
    next_to = (request.POST.get('next') or 'cart').strip().lower()
    if next_to == 'menu':
        return redirect('kahawa:menu')
    return redirect('kahawa:cart')


def _mark_gift_paid(gift, method: str) -> None:
    """Activate a gift card after successful payment (cash or M-Pesa)."""
    from django.utils import timezone as dj_tz

    gift.payment_status = 'PAID'
    gift.payment_method = method or gift.payment_method or ''
    gift.balance = gift.initial_balance
    gift.is_active = True
    if not gift.paid_at:
        gift.paid_at = dj_tz.now()
    gift.save(
        update_fields=[
            'payment_status',
            'payment_method',
            'balance',
            'is_active',
            'paid_at',
        ]
    )


def _mark_gift_unpaid(gift, *, failed: bool = False) -> None:
    """Keep card saved but inactive until paid."""
    gift.payment_status = 'FAILED' if failed else 'PENDING'
    gift.balance = Decimal('0')
    gift.is_active = False
    gift.paid_at = None
    gift.save(
        update_fields=['payment_status', 'balance', 'is_active', 'paid_at']
    )


def _start_gift_stk(gift, phone: str) -> dict:
    """Start M-Pesa STK for an unpaid gift card. Returns {ok, error?, …}."""
    from .services import mpesa as mpesa_service

    phone = _validate_kenyan_phone(phone) if phone else None
    if not phone:
        return {'ok': False, 'error': 'Enter a valid Kenyan phone for M-Pesa.'}

    if gift.purchaser_phone != phone:
        gift.purchaser_phone = phone
        gift.save(update_fields=['purchaser_phone'])

    result = mpesa_service.initiate_stk_push(
        phone=phone,
        amount=gift.initial_balance,
        account_ref=gift.code,
        description=f'Gift {gift.code}',
        kind='gift',
        ref_id=gift.id,
    )
    if not result.get('ok'):
        _mark_gift_unpaid(gift, failed=True)
        gift.payment_method = gift.PaymentMethod.MPESA
        gift.save(update_fields=['payment_method'])
        return {
            'ok': False,
            'error': result.get('error') or 'Could not start M-Pesa.',
        }

    gift.payment_status = 'PENDING'
    gift.payment_method = gift.PaymentMethod.MPESA
    gift.balance = Decimal('0')
    gift.is_active = False
    gift.mpesa_checkout_request_id = result['checkout_request_id']
    gift.save(
        update_fields=[
            'payment_status',
            'payment_method',
            'balance',
            'is_active',
            'mpesa_checkout_request_id',
        ]
    )
    cache.set(f'kahawa_gift_start:{gift.code}', time.time(), timeout=600)
    return {
        'ok': True,
        'checkout_request_id': result['checkout_request_id'],
        'customer_message': result.get('customer_message') or 'STK prompt sent.',
        'mock': bool(result.get('mock')),
    }


@rate_limit(key='gift_buy', limit=10, window=60)
@require_http_methods(['GET', 'POST'])
def gift_card_buy(request):
    """Purchase a gift card via M-Pesa; show previously bought cards."""
    from django.db.models import Q

    from .models import GiftCard

    amounts = getattr(settings, 'GIFT_CARD_AMOUNTS', [500, 1000, 2000, 5000])
    prefill = _checkout_prefill(request)
    error = ''
    if request.method == 'POST':
        try:
            amount = Decimal(str(request.POST.get('amount') or '0'))
        except (InvalidOperation, TypeError, ValueError):
            amount = Decimal('0')
        allowed = {Decimal(str(a)) for a in amounts}
        if amount not in allowed:
            error = 'Choose a gift card amount.'
        else:
            phone = _validate_kenyan_phone(request.POST.get('phone') or '')
            if not phone:
                error = 'Enter a valid Kenyan phone number (07… or 01…).'
            else:
                recipient = (request.POST.get('recipient_phone') or '').strip()
                recipient_fmt = ''
                if recipient:
                    recipient_fmt = _validate_kenyan_phone(recipient) or ''
                    if not recipient_fmt:
                        error = 'Recipient phone looks invalid.'

                if not error:
                    gift = GiftCard(
                        initial_balance=amount,
                        balance=Decimal('0'),
                        purchaser_phone=phone,
                        recipient_phone=recipient_fmt,
                        payment_status='PENDING',
                        payment_method=GiftCard.PaymentMethod.MPESA,
                        is_active=False,
                    )
                    if request.user.is_authenticated:
                        gift.created_by = request.user
                    gift.save()
                    _remember_gift_code(request, gift.code)

                    result = _start_gift_stk(gift, phone)
                    if not result.get('ok'):
                        error = result.get('error') or 'Could not start payment.'
                    else:
                        return redirect(
                            'kahawa:gift_card_pending',
                            code=gift.code,
                        )

    my_cards = GiftCard.objects.none()
    q = Q()
    if request.user.is_authenticated:
        q |= Q(created_by=request.user)
        profile = getattr(request.user, 'profile', None)
        if profile is None:
            try:
                profile = CustomerProfile.objects.get(user=request.user)
            except CustomerProfile.DoesNotExist:
                profile = None
        if profile and profile.phone:
            q |= Q(purchaser_phone=profile.phone) | Q(recipient_phone=profile.phone)

    session_codes = request.session.get('gift_card_codes') or []
    if session_codes:
        q |= Q(code__in=session_codes)

    if q:
        my_cards = GiftCard.objects.filter(q).distinct().order_by('-created_at')[:30]

    return render(
        request,
        'store/gift_card.html',
        {
            'amounts': amounts,
            'prefill': prefill,
            'error': error,
            'my_cards': my_cards,
            'is_authenticated': request.user.is_authenticated,
        },
    )


def _remember_gift_code(request, code: str) -> None:
    codes = list(request.session.get('gift_card_codes') or [])
    code = (code or '').upper()
    if code and code not in codes:
        codes.insert(0, code)
        request.session['gift_card_codes'] = codes[:20]
        request.session.modified = True


def _gift_whatsapp_url(gift) -> str:
    from urllib.parse import quote

    text = (
        f"Kahawa gift card {gift.code}\n"
        f"Balance: KSh {int(gift.balance):,}\n"
        f"Redeem at checkout with this code."
    )
    wa = f'https://wa.me/?text={quote(text)}'
    if gift.recipient_phone:
        try:
            digits = format_kenyan_phone(gift.recipient_phone).lstrip('+')
            wa = f'https://wa.me/{digits}?text={quote(text)}'
        except Exception:
            pass
    return wa


def _can_view_gift_card(request, gift) -> bool:
    if request.user.is_staff:
        return True
    if request.user.is_authenticated and gift.created_by_id == request.user.id:
        return True
    codes = request.session.get('gift_card_codes') or []
    if gift.code in codes:
        return True
    phone = ''
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile is None:
            try:
                profile = CustomerProfile.objects.get(user=request.user)
            except CustomerProfile.DoesNotExist:
                profile = None
        if profile:
            phone = profile.phone or ''
    if phone and (
        _phones_match(gift.purchaser_phone, phone)
        or _phones_match(gift.recipient_phone, phone)
    ):
        return True
    return False


@require_GET
def gift_card_pending(request, code):
    from .models import GiftCard

    gift = get_object_or_404(GiftCard, code__iexact=code)
    _remember_gift_code(request, gift.code)
    return render(request, 'store/gift_card_pending.html', {'gift': gift})


@require_GET
def gift_card_status(request, code):
    """Poll gift card payment (mock + live)."""
    from django.conf import settings as dj_settings

    from .models import GiftCard
    from .services import mpesa as mpesa_service

    gift = get_object_or_404(GiftCard, code__iexact=code)
    _remember_gift_code(request, gift.code)
    if gift.payment_status == 'PENDING':
        started = cache.get(f'kahawa_gift_start:{gift.code}')
        elapsed = time.time() - float(started) if started else 0
        timeout = getattr(dj_settings, 'PAYMENT_TIMEOUT_SECONDS', 90)
        is_mock = str(gift.mpesa_checkout_request_id or '').startswith('ws_')

        if is_mock or not mpesa_service.is_live():
            if elapsed >= MOCK_PAYMENT_WAIT_SECONDS and elapsed < timeout:
                _mark_gift_paid(gift, gift.PaymentMethod.MPESA)
            elif elapsed >= timeout:
                _mark_gift_unpaid(gift, failed=True)
        elif elapsed >= timeout:
            _mark_gift_unpaid(gift, failed=True)

    gift.refresh_from_db()
    data = {
        'ok': True,
        'code': gift.code,
        'payment_status': gift.payment_status,
        'is_active': gift.is_active,
        'balance': str(gift.balance),
        'needs_payment': gift.needs_payment,
    }
    if gift.payment_status == 'PAID':
        data['redirect_url'] = reverse(
            'kahawa:gift_card_success', kwargs={'code': gift.code}
        )
    return JsonResponse(data)


@require_POST
def gift_card_retry(request, code):
    """Restart M-Pesa STK for an unpaid gift card."""
    from .models import GiftCard

    gift = get_object_or_404(GiftCard, code__iexact=code)
    _remember_gift_code(request, gift.code)
    wants_json = 'application/json' in (request.headers.get('Accept') or '')

    if gift.payment_status == 'PAID':
        if wants_json:
            return JsonResponse(
                {'ok': False, 'error': 'Gift card is already paid.'}, status=400
            )
        return redirect('kahawa:gift_card_success', code=gift.code)
    if not _can_view_gift_card(request, gift):
        if wants_json:
            return JsonResponse({'ok': False, 'error': 'Not allowed.'}, status=403)
        return redirect('kahawa:gift_card_buy')

    phone_raw = (request.POST.get('phone') or gift.purchaser_phone or '').strip()
    body = _parse_json_body(request) or {}
    if body.get('phone'):
        phone_raw = str(body.get('phone')).strip()

    result = _start_gift_stk(gift, phone_raw)
    if not result.get('ok'):
        if wants_json:
            return JsonResponse(
                {'ok': False, 'error': result.get('error') or 'Could not start M-Pesa.'},
                status=400,
            )
        from django.contrib import messages

        messages.error(request, result.get('error') or 'Could not start M-Pesa.')
        return redirect('kahawa:gift_card_success', code=gift.code)

    if wants_json:
        return JsonResponse(
            {
                'ok': True,
                'code': gift.code,
                'message': result.get('customer_message') or 'STK prompt sent.',
                'pending_url': reverse(
                    'kahawa:gift_card_pending', kwargs={'code': gift.code}
                ),
            }
        )
    return redirect('kahawa:gift_card_pending', code=gift.code)


@require_GET
def gift_card_success(request, code):
    """Gift card detail — code, balance, status, share."""
    from .models import GiftCard

    gift = get_object_or_404(GiftCard, code__iexact=code)
    _remember_gift_code(request, gift.code)
    if not _can_view_gift_card(request, gift):
        # Allow PAID cards that just finished checkout in this session
        if gift.payment_status != 'PAID':
            return redirect('kahawa:gift_card_buy')

    return render(
        request,
        'store/gift_card_success.html',
        {
            'gift': gift,
            'whatsapp_url': _gift_whatsapp_url(gift),
            'can_share': gift.payment_status == 'PAID' and gift.balance > 0,
        },
    )


def _reorder_items_payload(order: Order) -> list[dict]:
    items = []
    for item in order.items.all():
        if not item.product_id:
            continue
        custom = item.customization or {}
        items.append(
            {
                'productId': item.product_id,
                'name': item.product.name if item.product else 'Item',
                'image': (item.product.image_src if item.product else '') or '',
                'quantity': item.quantity,
                'unitPrice': float(item.unit_price),
                'customization': {
                    key: custom[key]
                    for key in ('size', 'milk', 'extra_shot')
                    if key in custom and (key != 'extra_shot' or custom.get(key))
                },
                'available': bool(item.product and item.product.is_available),
            }
        )
    return items


def _can_access_order(request, order: Order) -> bool:
    if request.user.is_authenticated and (
        order.user_id == request.user.id or request.user.is_staff
    ):
        return True
    # Guest access by knowing the order code (same as order_detail).
    return True


@require_GET
def reorder_data(request, order_code):
    """JSON cart items for 'Order again' — owner or guest by code."""
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product'),
        order_code__iexact=order_code,
    )
    if not _can_access_order(request, order):
        return JsonResponse({'ok': False, 'error': 'Not allowed.'}, status=403)

    items = _reorder_items_payload(order)
    available = [i for i in items if i['available']]
    return JsonResponse(
        {
            'ok': True,
            'order_code': order.order_code,
            'items': available,
            'skipped': len(items) - len(available),
        }
    )


@require_POST
def reorder(request, order_code):
    """POST API: return cart-ready items for an order (same payload as reorder-data)."""
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product'),
        order_code__iexact=order_code,
    )
    if not _can_access_order(request, order):
        return JsonResponse({'ok': False, 'error': 'Not allowed.'}, status=403)

    items = [i for i in _reorder_items_payload(order) if i['available']]
    return JsonResponse({'ok': True, 'order_code': order.order_code, 'items': items})


@require_GET
def privacy(request):
    return render(request, 'store/privacy.html')


@require_GET
def terms(request):
    return render(request, 'store/terms.html')


@require_GET
def allergens(request):
    products_with_allergens = (
        Product.objects.exclude(allergens='')
        .select_related('category')
        .order_by('category__name', 'name')
    )
    return render(
        request,
        'store/allergens.html',
        {'products_with_allergens': products_with_allergens},
    )
