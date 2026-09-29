"""Staff operations dashboard — day-to-day order processing."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, DecimalField, F, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce, ExtractHour, NullIf
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Order, OrderItem
from .permissions import (
    has_perm,
    is_cafe_admin,
    manage_nav_context,
    permission_required,
    user_permissions,
)
from .services.sms import send_order_cancelled_sms, send_sms


def _today_bounds():
    """Return (start, end) datetimes for 'today' in the active timezone."""
    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def _board_queryset():
    start, end = _today_bounds()
    items_qs = OrderItem.objects.select_related('product').order_by('id')
    # Hide unpaid M-Pesa checkout holds until paid; keep pay-later (prep_after_payment=False).
    visible = Q(payment_status=Order.PaymentStatus.PAID) | Q(
        prep_after_payment=False
    ) & ~Q(payment_status=Order.PaymentStatus.FAILED)
    return (
        Order.objects.exclude(status=Order.Status.CANCELLED)
        .filter(visible)
        .filter(
            Q(
                status__in=[
                    Order.Status.PENDING,
                    Order.Status.PREPARING,
                    Order.Status.READY,
                ]
            )
            | Q(created_at__gte=start, created_at__lt=end)
            # Completed during today's service, even if the order was opened yesterday.
            | Q(
                status=Order.Status.COMPLETED,
                updated_at__gte=start,
                updated_at__lt=end,
            )
        )
        .select_related('table')
        .prefetch_related(Prefetch('items', queryset=items_qs))
        .order_by('created_at')
    )


def _serialize_item(item: OrderItem) -> dict:
    custom = item.customization or {}
    bits = []
    if custom.get('size'):
        bits.append(str(custom['size']))
    if custom.get('milk'):
        bits.append(f"{custom['milk']} milk")
    if custom.get('extra_shot'):
        bits.append('Extra shot')
    for part in custom.get('components') or []:
        bits.append(f"{part.get('quantity') or 1}× {part.get('name') or 'Item'}")
    return {
        'quantity': item.quantity,
        'name': item.display_name,
        'customization': ' · '.join(bits),
        'line_total': str(item.line_total),
    }


STATUS_PERMISSION = {
    Order.Status.PREPARING: 'ops.status.preparing',
    Order.Status.READY: 'ops.status.ready',
    Order.Status.COMPLETED: 'ops.status.completed',
    Order.Status.CANCELLED: 'ops.cancel',
}


def _serialize_order(order: Order, perms: set[str] | None = None) -> dict:
    perms = perms if perms is not None else set()
    local_created = timezone.localtime(order.created_at)
    next_status = {
        Order.Status.PENDING: Order.Status.PREPARING,
        Order.Status.PREPARING: Order.Status.READY,
        Order.Status.READY: Order.Status.COMPLETED,
    }.get(order.status)

    next_label = {
        Order.Status.PREPARING: 'Mark Preparing',
        Order.Status.READY: 'Mark Ready',
        Order.Status.COMPLETED: 'Mark Completed',
    }.get(next_status)

    if next_status and STATUS_PERMISSION.get(next_status) not in perms:
        next_status = None
        next_label = None

    can_cancel = (
        order.status in (Order.Status.PENDING, Order.Status.PREPARING)
        and 'ops.cancel' in perms
    )
    is_unpaid = order.payment_status in (
        Order.PaymentStatus.PENDING,
        Order.PaymentStatus.FAILED,
    )
    can_collect = is_unpaid and 'ops.collect_payment' in perms

    return {
        'id': order.id,
        'order_code': order.order_code,
        'customer_name': order.customer_name,
        'phone': order.phone or '',
        'order_type': order.order_type,
        'order_type_label': order.get_order_type_display(),
        'source': order.source,
        'status': order.status,
        'status_label': order.get_status_display(),
        'payment_status': order.payment_status,
        'payment_label': order.get_payment_status_display(),
        'payment_method': order.payment_method or '',
        'payment_method_label': order.get_payment_method_display()
        if order.payment_method
        else '',
        'is_unpaid': is_unpaid,
        'delivery_location': order.delivery_location or '',
        'table_code': order.table.code if order.table_id else '',
        'table_label': order.table.label if order.table_id else '',
        'total_amount': str(order.total_amount),
        'cash_tendered': str(order.cash_tendered) if order.cash_tendered is not None else '',
        'cash_change': str(order.cash_change) if order.cash_change is not None else '',
        'created_at': local_created.isoformat(),
        'created_display': local_created.strftime('%H:%M'),
        'created_full': local_created.strftime('%d %b · %H:%M'),
        'items': [_serialize_item(i) for i in order.items.all()],
        'next_status': next_status,
        'next_label': next_label,
        'can_cancel': can_cancel,
        'can_collect': can_collect,
    }


def _analytics() -> dict:
    start, end = _today_bounds()
    today = Order.objects.filter(created_at__gte=start, created_at__lt=end)

    revenue = today.filter(
        payment_status=Order.PaymentStatus.PAID,
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

    counts = today.aggregate(
        total_orders=Count('id'),
        pending=Count('id', filter=Q(status=Order.Status.PENDING)),
        preparing=Count('id', filter=Q(status=Order.Status.PREPARING)),
        ready=Count('id', filter=Q(status=Order.Status.READY)),
    )

    top_products = list(
        OrderItem.objects.filter(
            order__created_at__gte=start,
            order__created_at__lt=end,
            order__payment_status=Order.PaymentStatus.PAID,
        )
        .values('product__name')
        .annotate(qty=Sum('quantity'))
        .order_by('-qty')[:5]
    )
    top_products_out = [
        {
            'name': row['product__name'] or 'Deleted product',
            'qty': row['qty'] or 0,
        }
        for row in top_products
    ]

    peak_row = (
        today.annotate(hour=ExtractHour('created_at'))
        .values('hour')
        .annotate(count=Count('id'))
        .order_by('-count', 'hour')
        .first()
    )
    peak_hour = None
    peak_hour_label = ''
    if peak_row and peak_row.get('hour') is not None:
        hour = int(peak_row['hour'])
        peak_hour = hour
        end_h = (hour + 1) % 24
        peak_hour_label = f'{hour:02d}:00–{end_h:02d}:00'

    return {
        'revenue': revenue,
        'revenue_display': f'{revenue:,.0f}',
        'total_orders': counts['total_orders'] or 0,
        'pending': counts['pending'] or 0,
        'preparing': counts['preparing'] or 0,
        'ready': counts['ready'] or 0,
        'date_label': timezone.localtime(start).strftime('%A, %d %b %Y'),
        'top_products': top_products_out,
        'peak_hour': peak_hour,
        'peak_hour_label': peak_hour_label,
        'peak_hour_count': (peak_row or {}).get('count') or 0,
    }


def _board_payload(user=None) -> dict:
    perms = user_permissions(user) if user is not None else set()
    analytics = _analytics()
    orders = list(_board_queryset())
    columns = {
        'PENDING': [],
        'PREPARING': [],
        'READY': [],
        'COMPLETED': [],
    }
    for order in orders:
        if order.status in columns:
            columns[order.status].append(_serialize_order(order, perms))

    paid_ids = [
        o.id
        for o in orders
        if o.payment_status == Order.PaymentStatus.PAID
        and o.status
        not in (Order.Status.COMPLETED, Order.Status.CANCELLED)
    ]

    show_analytics = 'analytics.view' in perms
    return {
        'ok': True,
        'analytics': {
            'revenue': str(analytics['revenue']) if show_analytics else '0',
            'revenue_display': analytics['revenue_display'] if show_analytics else '—',
            'total_orders': analytics['total_orders'] if show_analytics else 0,
            'pending': analytics['pending'],
            'preparing': analytics['preparing'],
            'ready': analytics['ready'],
            'date_label': analytics['date_label'],
            'top_products': analytics['top_products'] if show_analytics else [],
            'peak_hour': analytics['peak_hour'] if show_analytics else None,
            'peak_hour_label': analytics['peak_hour_label'] if show_analytics else '',
            'peak_hour_count': analytics['peak_hour_count'] if show_analytics else 0,
        },
        'columns': columns,
        'pending_ids': [o['id'] for o in columns['PENDING']],
        'paid_ids': paid_ids,
        'server_time': timezone.localtime().isoformat(),
        'can_collect_payment': 'ops.collect_payment' in perms,
        'can_create_order': 'ops.create_order' in perms,
    }


@permission_required('ops.view')
@require_GET
def staff_dashboard(request):
    import json
    from decimal import Decimal as D

    from .models import CafeTable, Product
    from .offers import live_packages

    ctx = manage_nav_context(request)
    products = []
    for p in (
        Product.objects.filter(is_available=True)
        .select_related('category')
        .order_by('category__name', 'name')
    ):
        products.append(
            {
                'id': p.id,
                'name': p.name,
                'price': float(p.price),
                'category': p.category.name,
            }
        )
    tables = list(
        CafeTable.objects.filter(is_active=True)
        .order_by('code')
        .values('code', 'label')
    )
    ctx.update(
        {
            'analytics': _analytics(),
            'initial_payload': _board_payload(request.user),
            'page': 'ops',
            'is_admin': is_cafe_admin(request.user),
            'counter_products_json': json.dumps(products),
            'counter_packages_json': json.dumps(
                [
                    {
                        'id': package.id,
                        'name': package.name,
                        'price': float(package.price),
                    }
                    for package in live_packages()
                ]
            ),
            'counter_tables_json': json.dumps(tables),
        }
    )
    return render(request, 'staff/dashboard.html', ctx)


@permission_required('ops.view')
@require_GET
def live_orders_api(request):
    return JsonResponse(_board_payload(request.user))


@permission_required('ops.view')
@require_POST
def update_order_status(request, order_id):
    """Advance (or set) an order status from the ops board."""
    try:
        body = request.body.decode('utf-8')
        data = json.loads(body) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = request.POST

    new_status = (data.get('status') or '').upper()
    allowed = {
        Order.Status.PENDING,
        Order.Status.PREPARING,
        Order.Status.READY,
        Order.Status.COMPLETED,
        Order.Status.CANCELLED,
    }
    if new_status not in allowed:
        return JsonResponse({'ok': False, 'error': 'Invalid status.'}, status=400)

    needed = STATUS_PERMISSION.get(new_status)
    if needed and not has_perm(request.user, needed):
        return JsonResponse(
            {'ok': False, 'error': 'You do not have permission for that action.'},
            status=403,
        )

    order = get_object_or_404(Order, pk=order_id)
    was_paid = order.payment_status == Order.PaymentStatus.PAID
    order.status = new_status
    update_fields = ['status', 'updated_at']

    if new_status == Order.Status.CANCELLED:
        order.cancelled_at = timezone.now()
        update_fields.append('cancelled_at')
        reason = (data.get('cancel_reason') or data.get('reason') or '').strip()[:200]
        if reason:
            order.cancel_reason = reason
            update_fields.append('cancel_reason')
        if was_paid:
            order.payment_status = Order.PaymentStatus.REFUNDED
            update_fields.append('payment_status')
        order.save(update_fields=update_fields)
        if not was_paid:
            from .loyalty import restore_order_discounts

            restore_order_discounts(order)

        notify = data.get('notify_sms', True)
        if notify in (True, '1', 'true', 'on', 1):
            if reason:
                send_order_cancelled_sms(order, reason=reason)
            else:
                send_order_cancelled_sms(order)
            # Optional custom SMS body from staff
            custom_sms = (data.get('sms_message') or '').strip()
            if custom_sms:
                send_sms(order.phone, custom_sms)
    else:
        # Kitchen progress only — payment is collected separately.
        order.save(update_fields=update_fields)

    order.refresh_from_db()
    from .activity import log_staff_activity
    from .models import StaffActivity

    log_staff_activity(
        request.user,
        StaffActivity.Action.ORDER_STATUS,
        f'Set {order.order_code} to {order.get_status_display()}',
        order_code=order.order_code,
        status=new_status,
    )
    payload = _board_payload(request.user)
    payload['order'] = _serialize_order(order, user_permissions(request.user))
    return JsonResponse(payload)


def _cash_settlement(raw, total: Decimal):
    """Return (tender, change, error). Change is what to hand back."""
    total = Decimal(total or 0).quantize(Decimal('0.01'))
    if total <= 0:
        return Decimal('0.00'), Decimal('0.00'), None
    text = '' if raw is None else str(raw).strip().replace(',', '')
    if not text:
        return None, None, 'Enter the cash received.'
    try:
        tender = Decimal(text).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None, None, 'Enter the cash received.'
    if tender < total:
        short = (total - tender).quantize(Decimal('0.01'))
        shown = int(short) if short == short.to_integral() else short
        return None, None, f'Cash is short by KSh {shown}.'
    change = (tender - total).quantize(Decimal('0.01'))
    return tender, change, None


def _mark_order_paid(order: Order, method: str, *, cash_tendered=None, cash_change=None) -> None:
    from .loyalty import apply_order_paid_loyalty

    order.payment_status = Order.PaymentStatus.PAID
    order.payment_method = method
    update_fields = ['payment_status', 'payment_method', 'paid_at', 'updated_at']
    if method == Order.PaymentMethod.CASH:
        order.cash_tendered = cash_tendered
        order.cash_change = cash_change
        update_fields.extend(['cash_tendered', 'cash_change'])
    if not order.paid_at:
        order.paid_at = timezone.now()
    order.save(update_fields=update_fields)
    apply_order_paid_loyalty(order)


@permission_required('ops.collect_payment')
@require_POST
def collect_order_payment(request, order_id):
    """Mark unpaid order paid (cash) or start M-Pesa STK."""
    try:
        body = request.body.decode('utf-8')
        data = json.loads(body) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = request.POST

    order = get_object_or_404(Order, pk=order_id)
    if order.payment_status == Order.PaymentStatus.PAID:
        return JsonResponse({'ok': False, 'error': 'Order is already paid.'}, status=400)
    if order.payment_status == Order.PaymentStatus.REFUNDED:
        return JsonResponse({'ok': False, 'error': 'Order was refunded.'}, status=400)

    method = (data.get('method') or 'cash').strip().lower()
    if method == 'cash':
        tender, change, cash_error = _cash_settlement(
            data.get('cash_received'), order.total_amount
        )
        if cash_error:
            return JsonResponse({'ok': False, 'error': cash_error}, status=400)
        _mark_order_paid(
            order,
            Order.PaymentMethod.CASH,
            cash_tendered=tender,
            cash_change=change,
        )
        from .activity import log_staff_activity
        from .models import StaffActivity

        log_staff_activity(
            request.user,
            StaffActivity.Action.ORDER_STATUS,
            f'Collected cash for {order.order_code}',
            order_code=order.order_code,
            payment_method='CASH',
        )
        payload = _board_payload(request.user)
        payload['order'] = _serialize_order(order, user_permissions(request.user))
        payload['ok'] = True
        payload['cash_tendered'] = str(tender)
        payload['cash_change'] = str(change)
        return JsonResponse(payload)

    if method == 'mpesa':
        from .views import _start_stk, _validate_kenyan_phone

        phone_raw = (data.get('phone') or order.phone or '').strip()
        phone = _validate_kenyan_phone(phone_raw) if phone_raw else None
        if not phone:
            return JsonResponse(
                {
                    'ok': False,
                    'error': 'Enter a valid Kenyan phone for M-Pesa.',
                },
                status=400,
            )
        if phone != order.phone:
            order.phone = phone
            order.save(update_fields=['phone'])
        result = _start_stk(order, phone=phone)
        if not result.get('ok'):
            return JsonResponse(
                {'ok': False, 'error': result.get('error') or 'Could not start M-Pesa.'},
                status=400,
            )
        order.refresh_from_db()
        payload = _board_payload(request.user)
        payload['order'] = _serialize_order(order, user_permissions(request.user))
        payload['ok'] = True
        payload['stk_started'] = True
        payload['message'] = result.get('customer_message') or 'STK prompt sent.'
        return JsonResponse(payload)

    return JsonResponse({'ok': False, 'error': 'Unknown payment method.'}, status=400)


@permission_required('ops.create_order')
@require_POST
def create_counter_order(request):
    """Staff-created walk-in / table order with pay-later, cash, or M-Pesa."""
    from .models import CafeTable, Product
    from .pricing import normalize_customization, unit_price_for_product
    from .views import _start_stk, _validate_kenyan_phone

    try:
        body = request.body.decode('utf-8')
        data = json.loads(body) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)

    items = data.get('items') or []
    if not isinstance(items, list) or not items:
        return JsonResponse({'ok': False, 'error': 'Add at least one item.'}, status=400)

    customer_name = (data.get('customer_name') or '').strip() or 'Walk-in'
    phone_raw = (data.get('phone') or '').strip()
    phone = ''
    if phone_raw:
        phone = _validate_kenyan_phone(phone_raw)
        if not phone:
            return JsonResponse(
                {'ok': False, 'error': 'Invalid phone number.'}, status=400
            )

    order_type = (data.get('order_type') or 'PICKUP').upper()
    if order_type not in (
        Order.OrderType.PICKUP,
        Order.OrderType.DINE_IN,
        Order.OrderType.DELIVERY,
    ):
        order_type = Order.OrderType.PICKUP

    table = None
    table_code = (data.get('table_code') or '').strip()
    if order_type == Order.OrderType.DINE_IN:
        if not table_code:
            return JsonResponse(
                {'ok': False, 'error': 'Select a table for dine-in.'}, status=400
            )
        table = CafeTable.objects.filter(code__iexact=table_code, is_active=True).first()
        if not table:
            return JsonResponse({'ok': False, 'error': 'Table not available.'}, status=400)
        if customer_name == 'Walk-in':
            customer_name = f'Table {table.code}'

    payment_mode = (data.get('payment_mode') or 'cash').strip().lower()
    if payment_mode not in ('later', 'cash', 'mpesa'):
        payment_mode = 'cash'
    if payment_mode == 'later' and order_type != Order.OrderType.DINE_IN:
        return JsonResponse(
            {
                'ok': False,
                'error': 'Pay later is only available for dine-in table orders.',
            },
            status=400,
        )
    if payment_mode == 'mpesa' and not phone:
        return JsonResponse(
            {'ok': False, 'error': 'Phone is required for M-Pesa.'}, status=400
        )

    line_payloads = []
    subtotal = Decimal('0.00')
    for raw in items:
        if raw.get('package_id') or raw.get('packageId'):
            from .offers import resolve_package_line

            line, error = resolve_package_line(raw)
            if error:
                return error
            line_payloads.append(line)
            subtotal += line['unit_price'] * line['quantity']
            continue
        try:
            product_id = int(raw.get('product_id') or raw.get('productId'))
            quantity = int(raw.get('quantity') or 0)
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'Invalid item.'}, status=400)
        if quantity < 1:
            return JsonResponse({'ok': False, 'error': 'Invalid quantity.'}, status=400)
        product = Product.objects.filter(pk=product_id, is_available=True).first()
        if not product:
            return JsonResponse(
                {'ok': False, 'error': 'A product is unavailable.'}, status=400
            )
        customization = normalize_customization(product, raw.get('customization'))
        unit = unit_price_for_product(product.price, customization)
        line_payloads.append(
            {
                'product': product,
                'quantity': quantity,
                'unit_price': unit,
                'tax_type': product.tax_type,
                'customization': customization,
            }
        )
        subtotal += unit * quantity

    from .tax import totals_for_lines

    totals = totals_for_lines(line_payloads, order_type, discount=Decimal('0'))
    cash_tendered = cash_change = None
    if payment_mode == 'cash':
        cash_tendered, cash_change, cash_error = _cash_settlement(
            data.get('cash_received'), totals['total']
        )
        if cash_error:
            return JsonResponse({'ok': False, 'error': cash_error}, status=400)
    order = Order.objects.create(
        customer_name=customer_name[:100],
        phone=phone,
        order_type=order_type,
        table=table,
        source=Order.Source.COUNTER,
        created_by=request.user,
        tax_amount=totals['tax'],
        total_amount=totals['total'],
        status=Order.Status.PENDING,
        payment_status=Order.PaymentStatus.PENDING,
        prep_after_payment=(payment_mode == 'mpesa'),
    )
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

    stk_message = ''
    if payment_mode == 'cash':
        _mark_order_paid(
            order,
            Order.PaymentMethod.CASH,
            cash_tendered=cash_tendered,
            cash_change=cash_change,
        )
    elif payment_mode == 'mpesa':
        result = _start_stk(order, phone=phone)
        if not result.get('ok'):
            from .loyalty import fail_and_cancel_unpaid_order

            fail_and_cancel_unpaid_order(
                order, reason='Could not start M-Pesa payment'
            )
            return JsonResponse(
                {
                    'ok': False,
                    'error': result.get('error') or 'Could not start M-Pesa.',
                },
                status=400,
            )
        stk_message = result.get('customer_message') or 'STK prompt sent.'
        order.refresh_from_db()

    from .activity import log_staff_activity
    from .models import StaffActivity

    log_staff_activity(
        request.user,
        StaffActivity.Action.ORDER_STATUS,
        f'Created counter order {order.order_code} ({payment_mode})',
        order_code=order.order_code,
        payment_mode=payment_mode,
    )

    payload = _board_payload(request.user)
    payload['order'] = _serialize_order(order, user_permissions(request.user))
    payload['ok'] = True
    payload['order_code'] = order.order_code
    if cash_tendered is not None:
        payload['cash_tendered'] = str(cash_tendered)
        payload['cash_change'] = str(cash_change)
    if stk_message:
        payload['message'] = stk_message
    return JsonResponse(payload)


def _money(amount) -> str:
    value = Decimal(amount or 0)
    if value == value.to_integral():
        return f'{int(value):,}'
    return f'{value:,.2f}'


def _bounds_for(day):
    start = timezone.make_aware(
        datetime.combine(day, datetime.min.time()),
        timezone.get_current_timezone(),
    )
    return start, start + timedelta(days=1)


@permission_required('ops.view')
@require_GET
def kitchen_ticket(request, order_code):
    from .receipts import kitchen_context

    order = get_object_or_404(
        Order.objects.select_related('table').prefetch_related('items__product'),
        order_code__iexact=order_code,
    )
    return render(
        request,
        'staff/kitchen_ticket.html',
        kitchen_context(order, autoprint=request.GET.get('print') == '1'),
    )


def _parse_report_date(raw: str):
    text = (raw or '').strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        return None


def _sales_period(request):
    """Resolve a report range in local time. End is exclusive."""
    today = timezone.localdate()
    period = (request.GET.get('period') or 'today').strip().lower()
    error = ''
    if period == 'yesterday':
        start_day = end_day = today - timedelta(days=1)
    elif period == 'week':
        start_day = today - timedelta(days=today.weekday())
        end_day = start_day + timedelta(days=6)
    elif period == 'month':
        start_day = today.replace(day=1)
        if start_day.month == 12:
            next_month = start_day.replace(year=start_day.year + 1, month=1, day=1)
        else:
            next_month = start_day.replace(month=start_day.month + 1, day=1)
        end_day = next_month - timedelta(days=1)
    elif period == 'custom':
        start_day = _parse_report_date(request.GET.get('from'))
        end_day = _parse_report_date(request.GET.get('to'))
        if start_day is None or end_day is None:
            error = 'Choose a start date and an end date.'
            period = 'today'
            start_day = end_day = today
        elif end_day < start_day:
            start_day, end_day = end_day, start_day
        if period == 'custom' and (end_day - start_day).days > 366:
            error = 'Choose a range of a year or less.'
            end_day = start_day + timedelta(days=366)
    else:
        period = 'today'
        start_day = end_day = today

    if start_day == end_day:
        label = start_day.strftime('%A, %d %b %Y')
    elif period == 'month':
        label = start_day.strftime('%B %Y')
    else:
        label = f"{start_day.strftime('%d %b %Y')} – {end_day.strftime('%d %b %Y')}"

    start, _end = _bounds_for(start_day)
    _start, end = _bounds_for(end_day)
    return {
        'period': period,
        'label': label,
        'error': error,
        'start': start,
        'end': end,
        'from_value': start_day.isoformat(),
        'to_value': end_day.isoformat(),
    }


def _sale_rows(qs, name_expr):
    line_total = F('unit_price') * F('quantity')
    rows = (
        qs.annotate(sale_name=name_expr)
        .values('sale_name')
        .annotate(
            qty=Sum('quantity'),
            revenue=Sum(
                line_total,
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        )
        .order_by('-revenue', 'sale_name')
    )
    return [
        {
            'name': row['sale_name'] or 'Item',
            'qty': row['qty'] or 0,
            'revenue': _money(row['revenue'] or 0),
        }
        for row in rows
    ]


def _sales_context(request, *, order_limit=300, unpaid_limit=30):
    """Paid sales for a period, plus product and package totals."""
    report = _sales_period(request)
    paid = Order.objects.filter(
        payment_status=Order.PaymentStatus.PAID,
        paid_at__gte=report['start'],
        paid_at__lt=report['end'],
    ).exclude(status=Order.Status.CANCELLED)

    def bucket(qs):
        total = qs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        return {'count': qs.count(), 'display': _money(total), 'total': total}

    cash = bucket(paid.filter(payment_method=Order.PaymentMethod.CASH))
    mpesa = bucket(paid.filter(payment_method=Order.PaymentMethod.MPESA))
    other = bucket(
        paid.exclude(
            payment_method__in=[Order.PaymentMethod.CASH, Order.PaymentMethod.MPESA]
        )
    )
    paid_total = cash['total'] + mpesa['total'] + other['total']
    tax = paid.aggregate(total=Sum('tax_amount'))['total'] or Decimal('0')
    discounts = paid.aggregate(total=Sum('discount_amount'))['total'] or Decimal('0')

    items = OrderItem.objects.filter(order__in=paid)
    products = _sale_rows(
        items.filter(product__isnull=False),
        Coalesce('product__name', Value('Product')),
    )
    packages = _sale_rows(
        items.filter(product__isnull=True).exclude(item_name=''),
        Coalesce(NullIf('item_name', Value('')), 'package__name', Value('Package')),
    )

    order_count = paid.count()
    paid_orders = paid.order_by('-paid_at')
    shown = list(paid_orders if order_limit is None else paid_orders[:order_limit])
    opened = Order.objects.filter(
        created_at__gte=report['start'],
        created_at__lt=report['end'],
    )
    unpaid = (
        Order.objects.filter(
            payment_status__in=[
                Order.PaymentStatus.PENDING,
                Order.PaymentStatus.FAILED,
            ]
        )
        .exclude(status=Order.Status.CANCELLED)
        .order_by('created_at')
    )
    unpaid_rows = unpaid if unpaid_limit is None else unpaid[:unpaid_limit]
    unpaid_total = unpaid.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    ctx = manage_nav_context(request)
    ctx.update(
        {
            'page': 'sales',
            'periods': (
                ('today', 'Today'),
                ('yesterday', 'Yesterday'),
                ('week', 'This week'),
                ('month', 'This month'),
            ),
            'period': report['period'],
            'period_label': report['label'],
            'error': report['error'],
            'from_value': report['from_value'],
            'to_value': report['to_value'],
            'cash': cash,
            'mpesa': mpesa,
            'other': other,
            'show_other': other['count'] > 0,
            'paid_total': _money(paid_total),
            'paid_count': order_count,
            'tax_display': _money(tax),
            'discount_display': _money(discounts),
            'show_discount': discounts > 0,
            'opened_count': opened.count(),
            'cancelled_count': opened.filter(status=Order.Status.CANCELLED).count(),
            'unpaid_count': unpaid.count(),
            'unpaid_total': _money(unpaid_total),
            'unpaid_orders': [
                {
                    'code': order.order_code,
                    'name': order.customer_name,
                    'when': timezone.localtime(order.created_at).strftime('%d %b · %H:%M'),
                    'total': _money(order.total_amount),
                }
                for order in unpaid_rows
            ],
            'products': products,
            'packages': packages,
            'orders_truncated': order_count > len(shown),
            'orders': [
                {
                    'code': order.order_code,
                    'name': order.customer_name,
                    'when': timezone.localtime(order.paid_at).strftime('%d %b · %H:%M'),
                    'method': order.get_payment_method_display() if order.payment_method else 'Paid',
                    'total': _money(order.total_amount),
                }
                for order in shown
            ],
        }
    )
    return ctx


@permission_required('analytics.view')
@require_GET
def sales_history(request):
    return render(request, 'staff/sales.html', _sales_context(request))


@permission_required('analytics.view')
@require_GET
def sales_pdf(request):
    from .sales_export import render_sales_pdf

    ctx = _sales_context(request, order_limit=None, unpaid_limit=None)
    start = ctx['from_value']
    end = ctx['to_value']
    filename = f'Kahawa-sales-{start}.pdf' if start == end else f'Kahawa-sales-{start}-to-{end}.pdf'
    response = HttpResponse(render_sales_pdf(ctx), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
