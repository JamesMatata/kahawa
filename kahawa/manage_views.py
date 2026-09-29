"""Custom management dashboard — catalog, tables, gift cards, team (no Django admin UI)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import CafeTable, Category, GiftCard, Package, PackageItem, Product, StaffProfile
from .permissions import (
    admin_required,
    is_cafe_staff,
    manage_nav_context,
    permission_required,
    staff_login_required,
)
from .ratelimit import rate_limit
from .tax import TAX_TYPE_CHOICES, normalize_tax_type

User = get_user_model()


def _ctx(request, **extra):
    ctx = manage_nav_context(request)
    ctx.update(extra)
    return ctx


def manage_entry(request):
    """
    /manage/ — single entry for cafe team.
    Logged-in staff → live ops; everyone else → login.
    """
    if request.user.is_authenticated and is_cafe_staff(request.user):
        return redirect('kahawa:staff_dashboard')
    return redirect('kahawa:staff_login')


@rate_limit(key='staff_login', limit=12, window=60)
@require_http_methods(['GET', 'POST'])
def staff_login(request):
    """Username/password login for cafe team."""
    if request.user.is_authenticated and is_cafe_staff(request.user):
        return redirect('kahawa:staff_dashboard')

    error = ''
    username = ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)
        if user is None:
            error = 'Incorrect username or password.'
        elif not is_cafe_staff(user):
            error = 'This account does not have staff access.'
        else:
            login(request, user)
            from .activity import log_staff_activity
            from .models import StaffActivity

            log_staff_activity(
                user,
                StaffActivity.Action.LOGIN,
                f'{user.get_username()} signed in to Manage',
            )
            next_url = request.GET.get('next') or request.POST.get('next') or ''
            if next_url.startswith('/manage'):
                return redirect(next_url)
            return redirect('kahawa:staff_dashboard')

    return render(
        request,
        'staff/login.html',
        {'error': error, 'username': username, 'next': request.GET.get('next', '')},
    )


@require_POST
def staff_logout(request):
    if request.user.is_authenticated:
        from .activity import log_staff_activity
        from .models import StaffActivity

        log_staff_activity(
            request.user,
            StaffActivity.Action.LOGOUT,
            f'{request.user.get_username()} signed out',
        )
    logout(request)
    return redirect('kahawa:staff_login')


# ── Products ───────────────────────────────────────────────────────────────


def _serialize_product(product: Product) -> dict:
    return {
        'id': product.id,
        'name': product.name,
        'description': product.description or '',
        'price': float(product.price),
        'category_id': product.category_id,
        'category_name': product.category.name if product.category_id else '',
        'image_url': product.image_url or '',
        'image_src': product.image_src,
        'has_upload': bool(product.image),
        'prep_minutes': product.prep_minutes,
        'allergens': product.allergens or '',
        'is_featured': product.is_featured,
        'is_available': product.is_available,
        'allow_size': product.allow_size,
        'allow_milk': product.allow_milk,
        'allow_extra_shot': product.allow_extra_shot,
        'tax_type': product.tax_type,
    }


def _save_product_from_request(request, product: Product | None) -> tuple[Product | None, str]:
    """Create/update product from POST (multipart). Returns (product, error)."""
    name = (request.POST.get('name') or '').strip()
    description = (request.POST.get('description') or '').strip()
    image_url = (request.POST.get('image_url') or '').strip()
    allergens = (request.POST.get('allergens') or '').strip()
    try:
        price = Decimal(str(request.POST.get('price') or '0'))
    except (InvalidOperation, TypeError, ValueError):
        price = Decimal('0')
    try:
        prep = int(request.POST.get('prep_minutes') or 8)
    except (TypeError, ValueError):
        prep = 8
    category_id = request.POST.get('category')
    is_featured = request.POST.get('is_featured') == 'on'
    is_available = request.POST.get('is_available') == 'on'
    allow_size = request.POST.get('allow_size') == 'on'
    allow_milk = request.POST.get('allow_milk') == 'on'
    allow_extra_shot = request.POST.get('allow_extra_shot') == 'on'
    tax_type = normalize_tax_type(request.POST.get('tax_type'))
    clear_image = request.POST.get('clear_image') == 'on'
    upload = request.FILES.get('image')

    if not name:
        return None, 'Name is required.'
    if price <= 0:
        return None, 'Enter a valid price.'
    category = Category.objects.filter(pk=category_id).first()
    if not category:
        return None, 'Choose a category.'
    if image_url and not (
        image_url.startswith('http://') or image_url.startswith('https://')
    ):
        return None, 'Image link must be a full http:// or https:// URL.'

    if product is None:
        product = Product(category=category)
    product.category = category
    product.name = name
    product.description = description
    product.price = price
    product.image_url = image_url
    product.prep_minutes = max(1, prep)
    product.allergens = allergens
    product.is_featured = is_featured
    product.is_available = is_available
    product.allow_size = allow_size
    product.allow_milk = allow_milk
    product.allow_extra_shot = allow_extra_shot
    product.tax_type = tax_type

    if clear_image and product.image:
        product.image.delete(save=False)
        product.image = None
    if upload:
        if product.image:
            product.image.delete(save=False)
        product.image = upload

    product.save()
    return product, ''


@permission_required('catalog.view')
@require_http_methods(['GET', 'POST'])
def manage_products(request):
    import json

    from .activity import log_staff_activity
    from .models import StaffActivity
    from .permissions import user_permissions

    perms = user_permissions(request.user)
    can_edit = 'catalog.edit' in perms
    error = ''
    reopen = ''
    reopen_id = ''
    draft = {}

    if request.method == 'POST' and can_edit:
        action = request.POST.get('action') or 'save'
        if action == 'save':
            product_id = request.POST.get('product_id') or None
            product = None
            if product_id:
                product = get_object_or_404(Product, pk=product_id)
            saved, error = _save_product_from_request(request, product)
            if not error and saved:
                log_staff_activity(
                    request.user,
                    StaffActivity.Action.PRODUCT_EDIT,
                    f'{"Created" if not product_id else "Updated"} {saved.name}',
                    product_id=saved.id,
                )
                messages.success(request, f'Saved {saved.name}.')
                return redirect('kahawa:manage_products')
            reopen = 'edit' if product_id else 'new'
            reopen_id = str(product_id or '')
            draft = {
                'id': reopen_id,
                'name': request.POST.get('name') or '',
                'description': request.POST.get('description') or '',
                'price': request.POST.get('price') or '',
                'category_id': request.POST.get('category') or '',
                'image_url': request.POST.get('image_url') or '',
                'prep_minutes': request.POST.get('prep_minutes') or '8',
                'allergens': request.POST.get('allergens') or '',
                'is_featured': request.POST.get('is_featured') == 'on',
                'is_available': request.POST.get('is_available') == 'on',
                'allow_size': request.POST.get('allow_size') == 'on',
                'allow_milk': request.POST.get('allow_milk') == 'on',
                'allow_extra_shot': request.POST.get('allow_extra_shot') == 'on',
                'tax_type': request.POST.get('tax_type') or 'B',
                'has_upload': bool(product.image) if product else False,
                'image_src': (product.image_src if product else '') or '',
            }
        elif action == 'delete':
            product = get_object_or_404(Product, pk=request.POST.get('product_id'))
            name = product.name
            if product.image:
                product.image.delete(save=False)
            product.delete()
            messages.success(request, f'Deleted {name}.')
            return redirect('kahawa:manage_products')

    products = list(
        Product.objects.select_related('category').order_by('category__name', 'name')
    )
    categories = list(Category.objects.order_by('name'))
    products_payload = [_serialize_product(p) for p in products]
    categories_payload = [{'id': c.id, 'name': c.name} for c in categories]

    return render(
        request,
        'staff/manage_products.html',
        _ctx(
            request,
            products=products,
            categories=categories,
            products_payload_json=json.dumps(products_payload),
            categories_payload_json=json.dumps(categories_payload),
            can_edit=can_edit,
            error=error,
            reopen=reopen,
            reopen_id=reopen_id,
            draft_json=json.dumps(draft),
            tax_types=TAX_TYPE_CHOICES,
            page='products',
        ),
    )


@permission_required('catalog.toggle')
@require_POST
def product_toggle_available(request, product_id):
    """Mark sold out / available."""
    product = get_object_or_404(Product, pk=product_id)
    product.is_available = not product.is_available
    product.save(update_fields=['is_available'])
    from .activity import log_staff_activity
    from .models import StaffActivity

    log_staff_activity(
        request.user,
        StaffActivity.Action.PRODUCT_TOGGLE,
        f'Marked {product.name} {"available" if product.is_available else "sold out"}',
        product_id=product.id,
        is_available=product.is_available,
    )
    messages.success(
        request,
        f'{product.name} is now {"available" if product.is_available else "sold out"}.',
    )
    return redirect('kahawa:manage_products')


@permission_required('catalog.edit')
@require_http_methods(['GET', 'POST'])
def product_edit(request, product_id=None):
    """Legacy URLs → products page drawers."""
    if product_id:
        return redirect(f"{reverse('kahawa:manage_products')}?edit={product_id}")
    return redirect(f"{reverse('kahawa:manage_products')}?new=1")


@permission_required('catalog.edit')
@require_POST
def product_delete(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    name = product.name
    if product.image:
        product.image.delete(save=False)
    product.delete()
    messages.success(request, f'Deleted {name}.')
    return redirect('kahawa:manage_products')


def _parse_local_dt(value: str):
    from datetime import datetime

    raw = (value or '').strip()
    if not raw:
        return None
    dt = datetime.fromisoformat(raw)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _parse_local_time(value: str):
    from datetime import datetime

    raw = (value or '').strip()
    if not raw:
        return None
    return datetime.strptime(raw, '%H:%M').time()


# ── Packages / offers ───────────────────────────────────────────────────────


_MON_FRI = [0, 1, 2, 3, 4]
_UI_SCHEDULES = {'ALWAYS', 'WEEKDAYS', 'CUSTOM'}


def _ui_schedule(mode, weekdays):
    days = sorted({int(day) for day in (weekdays or [])})
    if mode == Package.ScheduleMode.WEEKLY:
        return 'WEEKDAYS' if days == _MON_FRI else 'CUSTOM'
    return 'ALWAYS'


def _stored_schedule(choice, weekdays):
    days = []
    for day in weekdays:
        try:
            number = int(day)
        except (TypeError, ValueError):
            continue
        if 0 <= number <= 6 and number not in days:
            days.append(number)
    if choice == 'WEEKDAYS':
        return Package.ScheduleMode.WEEKLY, days or list(_MON_FRI)
    if choice == 'CUSTOM':
        return Package.ScheduleMode.WEEKLY, days
    return Package.ScheduleMode.ALWAYS, days


def _blank_package_form():
    return {
        'id': '',
        'name': '',
        'description': '',
        'price': '',
        'tax_type': 'B',
        'image_url': '',
        'image_ratio': Package.ImageRatio.WIDE,
        'image_src': '',
        'has_upload': False,
        'schedule_mode': Package.ScheduleMode.ALWAYS,
        'starts_at': '',
        'ends_at': '',
        'window_start': '',
        'window_end': '',
        'weekdays': [],
        'is_active': True,
        'items': [
            {'product_id': '', 'quantity': 1},
            {'product_id': '', 'quantity': 1},
        ],
    }


def _form_from_package(package):
    items = [
        {'product_id': row.product_id, 'quantity': row.quantity}
        for row in package.items.all()
    ]
    while len(items) < 2:
        items.append({'product_id': '', 'quantity': 1})
    price = package.price
    price_text = str(int(price)) if price == price.to_integral() else str(price)
    form = _blank_package_form()
    form.update(
        {
            'id': package.id,
            'name': package.name,
            'description': package.description,
            'price': price_text,
            'tax_type': package.tax_type or 'B',
            'image_url': package.image_url,
            'image_ratio': package.image_ratio or Package.ImageRatio.WIDE,
            'image_src': package.image_src,
            'has_upload': bool(package.image),
            'schedule_mode': _ui_schedule(package.schedule_mode, package.weekdays),
            'starts_at': (
                timezone.localtime(package.starts_at).strftime('%Y-%m-%dT%H:%M')
                if package.starts_at
                else ''
            ),
            'ends_at': (
                timezone.localtime(package.ends_at).strftime('%Y-%m-%dT%H:%M')
                if package.ends_at
                else ''
            ),
            'window_start': package.window_start.strftime('%H:%M') if package.window_start else '',
            'window_end': package.window_end.strftime('%H:%M') if package.window_end else '',
            'weekdays': [int(day) for day in (package.weekdays or [])],
            'is_active': package.is_active,
            'items': items,
        }
    )
    return form


def _form_from_post(request):
    weekdays = []
    for day in request.POST.getlist('weekdays'):
        try:
            weekdays.append(int(day))
        except (TypeError, ValueError):
            continue
    items = []
    for product_id, qty_raw in zip(
        request.POST.getlist('item_product'),
        request.POST.getlist('item_qty'),
    ):
        pid = int(product_id) if str(product_id).isdigit() else ''
        try:
            qty = int(qty_raw or 1)
        except (TypeError, ValueError):
            qty = 1
        items.append({'product_id': pid, 'quantity': max(qty, 1)})
    while len(items) < 2:
        items.append({'product_id': '', 'quantity': 1})
    schedule_mode = request.POST.get('schedule_mode') or 'ALWAYS'
    if schedule_mode not in _UI_SCHEDULES:
        schedule_mode = 'ALWAYS'
    form = _blank_package_form()
    form.update(
        {
            'id': (request.POST.get('package_id') or '').strip(),
            'name': (request.POST.get('name') or '').strip(),
            'description': (request.POST.get('description') or '').strip(),
            'price': (request.POST.get('price') or '').strip(),
            'tax_type': (request.POST.get('tax_type') or 'B').strip() or 'B',
            'image_url': (request.POST.get('image_url') or '').strip(),
            'image_ratio': (
                request.POST.get('image_ratio')
                if request.POST.get('image_ratio') in Package.ImageRatio.values
                else Package.ImageRatio.WIDE
            ),
            'schedule_mode': schedule_mode,
            'starts_at': (request.POST.get('starts_at') or '').strip(),
            'ends_at': (request.POST.get('ends_at') or '').strip(),
            'window_start': (request.POST.get('window_start') or '').strip(),
            'window_end': (request.POST.get('window_end') or '').strip(),
            'weekdays': weekdays,
            'is_active': request.POST.get('is_active') == 'on',
            'items': items,
        }
    )
    return form


@permission_required('catalog.edit')
@require_http_methods(['GET', 'POST'])
def manage_packages(request):
    error = ''
    package_form = _blank_package_form()
    open_drawer = False
    if request.method == 'GET' and request.GET.get('edit'):
        editing = Package.objects.prefetch_related('items__product').filter(
            pk=request.GET.get('edit')
        ).first()
        if editing:
            package_form = _form_from_package(editing)
            open_drawer = True
    elif request.method == 'GET' and request.GET.get('new'):
        open_drawer = True

    if request.method == 'POST':
        action = request.POST.get('action') or 'save'
        if action == 'toggle':
            package = get_object_or_404(Package, pk=request.POST.get('package_id'))
            package.is_active = not package.is_active
            package.save(update_fields=['is_active'])
            messages.success(
                request,
                f'{package.name} is now {"on" if package.is_active else "off"}.',
            )
            return redirect('kahawa:manage_packages')
        if action == 'delete':
            package = get_object_or_404(Package, pk=request.POST.get('package_id'))
            name = package.name
            if package.image:
                package.image.delete(save=False)
            package.delete()
            messages.success(request, f'Deleted {name}.')
            return redirect('kahawa:manage_packages')

        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        image_url = (request.POST.get('image_url') or '').strip()
        upload = request.FILES.get('image')
        clear_image = request.POST.get('clear_image') == 'on'
        schedule_choice = request.POST.get('schedule_mode') or 'ALWAYS'
        try:
            price = Decimal(str(request.POST.get('price') or '0'))
        except (InvalidOperation, TypeError, ValueError):
            price = Decimal('0')
        product_ids = request.POST.getlist('item_product')
        qtys = request.POST.getlist('item_qty')
        rows = []
        for product_id, qty_raw in zip(product_ids, qtys):
            if not product_id:
                continue
            try:
                qty = int(qty_raw or 1)
            except (TypeError, ValueError):
                qty = 0
            product = Product.objects.filter(pk=product_id).first()
            if product and qty > 0:
                rows.append((product, qty))

        if schedule_choice not in _UI_SCHEDULES:
            schedule_choice = 'ALWAYS'
        try:
            starts_at = _parse_local_dt(request.POST.get('starts_at'))
            ends_at = _parse_local_dt(request.POST.get('ends_at'))
            window_start = _parse_local_time(request.POST.get('window_start'))
            window_end = _parse_local_time(request.POST.get('window_end'))
        except ValueError:
            starts_at = ends_at = window_start = window_end = None
            error = 'Check the dates and times.'
        weekdays = []
        for day in request.POST.getlist('weekdays'):
            try:
                weekdays.append(int(day))
            except (TypeError, ValueError):
                continue
        schedule_mode, weekdays = _stored_schedule(schedule_choice, weekdays)

        if not error and not name:
            error = 'Name is required.'
        elif not error and price <= 0:
            error = 'Enter the package price.'
        elif not error and len(rows) < 2:
            error = 'A package needs at least two products.'
        elif not error and schedule_mode == Package.ScheduleMode.WEEKLY and not weekdays:
            error = 'Choose at least one day.'
        elif not error and image_url and not (
            image_url.startswith('http://') or image_url.startswith('https://')
        ):
            error = 'Image link must be a full http:// or https:// URL.'
        elif not error and upload and (upload.content_type or '').lower() not in {
            'image/jpeg',
            'image/png',
            'image/webp',
        }:
            error = 'Upload a JPG, PNG, or WebP photo.'
        elif not error and upload and upload.size > 5 * 1024 * 1024:
            error = 'Photo must be 5 MB or smaller.'
        if not error:
            existing = Package.objects.filter(pk=request.POST.get('package_id') or 0).first()
            keeps_upload = bool(existing and existing.image and not clear_image)
            if not upload and not image_url and not keeps_upload:
                error = 'Add a photo, or paste an image link.'

        if not error:
            package_id = request.POST.get('package_id') or None
            package = Package.objects.filter(pk=package_id).first() if package_id else None
            if package is None:
                package = Package()
            package.name = name
            package.description = description
            package.price = price
            package.tax_type = normalize_tax_type(request.POST.get('tax_type'))
            package.image_url = image_url
            package.image_ratio = Package.ImageRatio.WIDE
            if upload:
                if package.image:
                    package.image.delete(save=False)
                package.image = upload
            elif clear_image and package.image:
                package.image.delete(save=False)
                package.image = None
            package.is_active = request.POST.get('is_active') == 'on'
            package.schedule_mode = schedule_mode
            package.starts_at = starts_at
            package.ends_at = ends_at
            package.weekdays = weekdays
            package.window_start = window_start if schedule_mode == Package.ScheduleMode.WEEKLY else None
            package.window_end = window_end if schedule_mode == Package.ScheduleMode.WEEKLY else None
            with transaction.atomic():
                package.save()
                package.items.all().delete()
                PackageItem.objects.bulk_create(
                    [
                        PackageItem(package=package, product=product, quantity=qty)
                        for product, qty in rows
                    ]
                )
            messages.success(request, f'Saved {package.name}.')
            return redirect('kahawa:manage_packages')
        package_form = _form_from_post(request)
        existing = Package.objects.filter(pk=package_form.get('id') or 0).first()
        if existing and existing.image and request.POST.get('clear_image') != 'on' and not upload:
            package_form['has_upload'] = True
            package_form['image_src'] = existing.image_src
        elif image_url:
            package_form['image_src'] = image_url
        open_drawer = True

    packages = list(Package.objects.prefetch_related('items__product').order_by('name'))
    products = list(Product.objects.order_by('name'))
    return render(
        request,
        'staff/manage_packages.html',
        _ctx(
            request,
            packages=packages,
            products=products,
            package_form=package_form,
            open_drawer=open_drawer,
            error=error,
            tax_types=TAX_TYPE_CHOICES,
            weekdays=[
                (0, 'Mon'),
                (1, 'Tue'),
                (2, 'Wed'),
                (3, 'Thu'),
                (4, 'Fri'),
                (5, 'Sat'),
                (6, 'Sun'),
            ],
            page='packages',
        ),
    )


# ── Categories ──────────────────────────────────────────────────────────────


@permission_required('categories.manage')
@require_http_methods(['GET', 'POST'])
def manage_categories(request):
    error = ''
    if request.method == 'POST':
        action = request.POST.get('action') or 'create'
        if action == 'create':
            name = (request.POST.get('name') or '').strip()
            if not name:
                error = 'Category name is required.'
            else:
                slug = slugify(name)
                if Category.objects.filter(slug=slug).exists():
                    error = 'A category with that name already exists.'
                else:
                    Category.objects.create(
                        name=name,
                        slug=slug,
                        is_featured=request.POST.get('is_featured') == 'on',
                    )
                    messages.success(request, f'Created {name}.')
                    return redirect('kahawa:manage_categories')
        elif action == 'toggle_featured':
            cat = get_object_or_404(Category, pk=request.POST.get('category_id'))
            cat.is_featured = not cat.is_featured
            cat.save(update_fields=['is_featured'])
            return redirect('kahawa:manage_categories')
        elif action == 'delete':
            cat = get_object_or_404(Category, pk=request.POST.get('category_id'))
            product_count = cat.products.count()
            confirm_products = request.POST.get('confirm_products') == '1'
            if product_count and not confirm_products:
                messages.error(
                    request,
                    f'“{cat.name}” has {product_count} product'
                    f'{"s" if product_count != 1 else ""}. Confirm deleting them too.',
                )
                return redirect('kahawa:manage_categories')

            name = cat.name
            # CASCADE removes products when the category is deleted
            cat.delete()
            if product_count:
                messages.success(
                    request,
                    f'Deleted {name} and {product_count} product'
                    f'{"s" if product_count != 1 else ""}.',
                )
            else:
                messages.success(request, f'Deleted {name}.')
            return redirect('kahawa:manage_categories')

    from django.db.models import Count

    categories = Category.objects.annotate(product_count=Count('products')).order_by(
        'name'
    )

    return render(
        request,
        'staff/manage_categories.html',
        _ctx(request, categories=categories, error=error, page='categories'),
    )


# ── Tables ──────────────────────────────────────────────────────────────────


@permission_required('tables.manage')
@require_http_methods(['GET', 'POST'])
def manage_tables(request):
    import json

    error = ''
    if request.method == 'POST':
        action = request.POST.get('action') or 'create'
        if action == 'create':
            code = slugify(request.POST.get('code') or '')
            label = (request.POST.get('label') or '').strip()
            if not code or not label:
                error = 'Code and label are required.'
            elif CafeTable.objects.filter(code__iexact=code).exists():
                error = 'That table code already exists.'
            else:
                CafeTable.objects.create(code=code, label=label, is_active=True)
                messages.success(request, f'Table {code} created.')
                return redirect('kahawa:manage_tables')
        elif action == 'edit':
            table = get_object_or_404(CafeTable, pk=request.POST.get('table_id'))
            label = (request.POST.get('label') or '').strip()
            if not label:
                error = 'Label is required.'
            else:
                table.label = label[:60]
                table.save(update_fields=['label'])
                messages.success(request, f'Table {table.code} updated.')
                return redirect('kahawa:manage_tables')
        elif action == 'toggle':
            table = get_object_or_404(CafeTable, pk=request.POST.get('table_id'))
            table.is_active = not table.is_active
            table.save(update_fields=['is_active'])
            if table.is_active:
                messages.success(request, f'Table {table.code} is active again.')
            else:
                messages.success(request, f'Table {table.code} taken offline.')
            return redirect('kahawa:manage_tables')
        elif action == 'delete':
            # Soft-deactivate instead of hard delete (keeps order history)
            table = get_object_or_404(CafeTable, pk=request.POST.get('table_id'))
            table.is_active = False
            table.save(update_fields=['is_active'])
            messages.success(request, f'Table {table.code} taken offline.')
            return redirect('kahawa:manage_tables')

    tables = list(CafeTable.objects.order_by('code'))
    site = request.build_absolute_uri('/')[:-1]

    tables_payload = [
        {
            'id': t.id,
            'code': t.code,
            'label': t.label,
            'is_active': t.is_active,
            'url': f"{site}{reverse('kahawa:table_entry', kwargs={'code': t.code})}",
        }
        for t in tables
    ]
    return render(
        request,
        'staff/manage_tables.html',
        _ctx(
            request,
            tables=tables,
            tables_payload_json=json.dumps(tables_payload),
            error=error,
            page='tables',
            site_url=site,
        ),
    )


# ── Gift cards ──────────────────────────────────────────────────────────────


def _gift_status_label(card: GiftCard) -> str:
    if card.payment_status == 'PAID' and card.is_active:
        return 'Active'
    if card.payment_status == 'PAID' and not card.is_active:
        return 'Inactive'
    if card.payment_status == 'PENDING':
        return 'Awaiting payment'
    return 'Unpaid'


def _serialize_gift_card(card: GiftCard) -> dict:
    spends = []
    spent_total = Decimal('0')
    for order in card.orders.all():
        amt = order.gift_card_amount or Decimal('0')
        spent_total += amt
        local = timezone.localtime(order.created_at)
        spends.append(
            {
                'order_code': order.order_code,
                'customer_name': order.customer_name,
                'amount': float(amt),
                'order_total': float(order.total_amount),
                'status': order.status,
                'status_label': order.get_status_display(),
                'payment_status': order.payment_status,
                'payment_label': order.get_payment_status_display(),
                'created_display': local.strftime('%d %b · %H:%M'),
            }
        )
    remaining = Decimal(card.balance or 0)
    initial = Decimal(card.initial_balance or 0)
    return {
        'id': card.id,
        'code': card.code,
        'initial': float(initial),
        'balance': float(remaining),
        'spent': float(max(initial - remaining, Decimal('0'))),
        'spent_orders': float(spent_total),
        'is_active': card.is_active,
        'needs_payment': card.needs_payment,
        'payment_status': card.payment_status,
        'payment_label': card.get_payment_status_display(),
        'status_label': _gift_status_label(card),
        'payment_method': card.payment_method or '',
        'payment_method_label': card.get_payment_method_display()
        if card.payment_method
        else '',
        'purchaser_phone': card.purchaser_phone or '',
        'recipient_phone': card.recipient_phone or '',
        'created_by': (
            card.created_by.get_username() if card.created_by_id else ''
        ),
        'created_display': timezone.localtime(card.created_at).strftime(
            '%d %b %Y · %H:%M'
        ),
        'paid_display': (
            timezone.localtime(card.paid_at).strftime('%d %b %Y · %H:%M')
            if card.paid_at
            else ''
        ),
        'spends': spends,
    }


@permission_required('gifts.manage')
@require_http_methods(['GET', 'POST'])
def manage_gift_cards(request):
    import json

    from django.db.models import Prefetch

    from .models import Order, StaffActivity
    from .views import _mark_gift_paid, _start_gift_stk, _validate_kenyan_phone

    error = ''
    paying_code = (request.GET.get('paying') or '').strip().upper()
    if request.method == 'POST':
        action = request.POST.get('action') or 'issue'
        if action == 'issue':
            try:
                amount = Decimal(str(request.POST.get('amount') or '0'))
            except (InvalidOperation, TypeError, ValueError):
                amount = Decimal('0')
            issue_mode = (request.POST.get('issue_mode') or 'gift').strip().lower()
            phone_raw = (request.POST.get('phone') or '').strip()

            if amount < 100:
                error = 'Minimum issue amount is KSh 100.'
            elif issue_mode not in ('gift', 'cash', 'mpesa'):
                error = 'Choose how this card is issued.'
            else:
                phone = ''
                if phone_raw:
                    phone = _validate_kenyan_phone(phone_raw) or ''
                    if not phone:
                        error = 'Enter a valid Kenyan phone (07… or 01…).'
                else:
                    error = 'Customer phone is required.'

            if not error:
                from .activity import log_staff_activity

                if issue_mode == 'gift':
                    gift = GiftCard(
                        initial_balance=amount,
                        balance=amount,
                        payment_status='PAID',
                        payment_method=GiftCard.PaymentMethod.COMPLIMENTARY,
                        paid_at=timezone.now(),
                        is_active=True,
                        purchaser_phone=phone,
                        created_by=request.user,
                    )
                    gift.save()
                    log_staff_activity(
                        request.user,
                        StaffActivity.Action.GIFT_ISSUE,
                        f'Issued complimentary {gift.code} · KSh {int(amount)}',
                        code=gift.code,
                        amount=str(amount),
                        mode='gift',
                    )
                    messages.success(
                        request, f'Issued {gift.code} · KSh {int(amount)} (gift).'
                    )
                    return redirect('kahawa:manage_gift_cards')

                if issue_mode == 'cash':
                    gift = GiftCard(
                        initial_balance=amount,
                        balance=Decimal('0'),
                        payment_status='PENDING',
                        payment_method=GiftCard.PaymentMethod.CASH,
                        is_active=False,
                        purchaser_phone=phone,
                        created_by=request.user,
                    )
                    gift.save()
                    _mark_gift_paid(gift, GiftCard.PaymentMethod.CASH)
                    log_staff_activity(
                        request.user,
                        StaffActivity.Action.GIFT_ISSUE,
                        f'Sold {gift.code} for cash · KSh {int(amount)}',
                        code=gift.code,
                        amount=str(amount),
                        mode='cash',
                    )
                    messages.success(
                        request, f'Sold {gift.code} · KSh {int(amount)} (cash).'
                    )
                    return redirect('kahawa:manage_gift_cards')

                # mpesa
                gift = GiftCard(
                    initial_balance=amount,
                    balance=Decimal('0'),
                    payment_status='PENDING',
                    payment_method=GiftCard.PaymentMethod.MPESA,
                    is_active=False,
                    purchaser_phone=phone,
                    created_by=request.user,
                )
                gift.save()
                result = _start_gift_stk(gift, phone)
                log_staff_activity(
                    request.user,
                    StaffActivity.Action.GIFT_ISSUE,
                    f'Started M-Pesa sale for {gift.code} · KSh {int(amount)}',
                    code=gift.code,
                    amount=str(amount),
                    mode='mpesa',
                    stk_ok=bool(result.get('ok')),
                )
                if not result.get('ok'):
                    messages.warning(
                        request,
                        f'{gift.code} saved unpaid. '
                        f'{result.get("error") or "M-Pesa did not start — collect payment later."}',
                    )
                    return redirect('kahawa:manage_gift_cards')
                messages.info(
                    request,
                    result.get('customer_message')
                    or f'STK sent for {gift.code}. Waiting for payment…',
                )
                return redirect(
                    f"{reverse('kahawa:manage_gift_cards')}?paying={gift.code}"
                )

        elif action == 'deactivate':
            gift = get_object_or_404(GiftCard, pk=request.POST.get('gift_id'))
            if gift.payment_status != 'PAID':
                messages.error(request, 'Only paid cards can be deactivated.')
                return redirect('kahawa:manage_gift_cards')
            gift.is_active = False
            gift.save(update_fields=['is_active'])
            messages.success(request, f'{gift.code} deactivated.')
            return redirect('kahawa:manage_gift_cards')

    spend_qs = (
        Order.objects.filter(gift_card_amount__gt=0)
        .order_by('-created_at')
        .only(
            'id',
            'order_code',
            'customer_name',
            'gift_card_amount',
            'total_amount',
            'status',
            'payment_status',
            'created_at',
            'gift_card_id',
        )
    )
    cards = list(
        GiftCard.objects.select_related('created_by')
        .prefetch_related(Prefetch('orders', queryset=spend_qs))
        .order_by('-created_at')[:100]
    )
    cards_payload = [_serialize_gift_card(card) for card in cards]

    return render(
        request,
        'staff/manage_gift_cards.html',
        _ctx(
            request,
            cards=cards,
            cards_payload_json=json.dumps(cards_payload),
            error=error,
            paying_code=paying_code,
            page='gifts',
        ),
    )


@permission_required('gifts.manage')
@require_POST
def collect_gift_payment(request, gift_id):
    """Mark unpaid gift card paid (cash) or start / retry M-Pesa STK."""
    import json

    from django.http import JsonResponse

    from .views import _mark_gift_paid, _start_gift_stk, _validate_kenyan_phone

    try:
        body = request.body.decode('utf-8')
        data = json.loads(body) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = request.POST

    gift = get_object_or_404(GiftCard, pk=gift_id)
    if gift.payment_status == 'PAID':
        return JsonResponse({'ok': False, 'error': 'Gift card is already paid.'}, status=400)

    method = (data.get('method') or 'cash').strip().lower()
    if method == 'cash':
        _mark_gift_paid(gift, GiftCard.PaymentMethod.CASH)
        from .activity import log_staff_activity
        from .models import StaffActivity

        log_staff_activity(
            request.user,
            StaffActivity.Action.GIFT_ISSUE,
            f'Collected cash for {gift.code}',
            code=gift.code,
            method='CASH',
        )
        return JsonResponse(
            {
                'ok': True,
                'card': _serialize_gift_card(gift),
                'message': f'{gift.code} marked paid (cash).',
            }
        )

    if method == 'mpesa':
        phone_raw = (data.get('phone') or gift.purchaser_phone or '').strip()
        phone = _validate_kenyan_phone(phone_raw) if phone_raw else None
        if not phone:
            return JsonResponse(
                {
                    'ok': False,
                    'error': 'Enter a valid Kenyan phone for M-Pesa.',
                },
                status=400,
            )
        result = _start_gift_stk(gift, phone)
        if not result.get('ok'):
            return JsonResponse(
                {
                    'ok': False,
                    'error': result.get('error') or 'Could not start M-Pesa.',
                    'card': _serialize_gift_card(gift),
                },
                status=400,
            )
        gift.refresh_from_db()
        return JsonResponse(
            {
                'ok': True,
                'stk_started': True,
                'code': gift.code,
                'card': _serialize_gift_card(gift),
                'message': result.get('customer_message') or 'STK prompt sent.',
                'status_url': f'/gift-cards/{gift.code}/status/',
            }
        )

    return JsonResponse({'ok': False, 'error': 'Unknown payment method.'}, status=400)


# ── Team (admin only) ───────────────────────────────────────────────────────


def _apply_display_name(user, display_name: str) -> None:
    display_name = (display_name or '').strip()
    if display_name:
        parts = display_name.split(None, 1)
        user.first_name = parts[0]
        user.last_name = parts[1] if len(parts) > 1 else ''
    else:
        user.first_name = ''
        user.last_name = ''
    user.save(update_fields=['first_name', 'last_name'])


def _posted_role_slugs(request) -> list[str]:
    return [s.strip() for s in request.POST.getlist('roles') if s.strip()]


def _posted_permissions(request) -> list[str]:
    from .staff_roles import parse_permission_codes

    return parse_permission_codes(request.POST.getlist('permissions'))


@admin_required
@require_http_methods(['GET', 'POST'])
def manage_team(request):
    from .activity import log_staff_activity
    from .models import StaffActivity, StaffRole
    from .staff_roles import apply_roles_and_permissions, ensure_system_roles

    ensure_system_roles()
    error = ''
    form_mode = ''
    if request.method == 'POST':
        action = request.POST.get('action') or 'create'
        form_mode = action
        if action == 'create':
            username = (request.POST.get('username') or '').strip().lower()
            display_name = (request.POST.get('display_name') or '').strip()
            password = request.POST.get('password') or ''
            role_slugs = _posted_role_slugs(request)
            permission_codes = _posted_permissions(request)

            if not username or not password:
                error = 'Username and password are required.'
            elif not role_slugs:
                error = 'Select at least one role.'
            elif not permission_codes:
                error = 'Select at least one permission.'
            elif User.objects.filter(username=username).exists():
                error = 'That username is taken.'
            else:
                try:
                    validate_password(password)
                except ValidationError as exc:
                    error = ' '.join(exc.messages)
                else:
                    with transaction.atomic():
                        user = User.objects.create_user(
                            username=username,
                            password=password,
                            is_staff=True,
                        )
                        _apply_display_name(user, display_name)
                        profile = StaffProfile.objects.create(
                            user=user,
                            display_name=display_name,
                            created_by=request.user,
                            is_active=True,
                        )
                        apply_roles_and_permissions(
                            profile, role_slugs, permission_codes
                        )
                    log_staff_activity(
                        request.user,
                        StaffActivity.Action.TEAM_CREATE,
                        f'Created {username} ({", ".join(role_slugs)})',
                        username=username,
                        roles=role_slugs,
                        permissions=permission_codes,
                    )
                    messages.success(request, f'Created {username}.')
                    return redirect('kahawa:manage_team')

        elif action == 'edit':
            profile = get_object_or_404(
                StaffProfile.objects.prefetch_related('roles'),
                pk=request.POST.get('profile_id'),
            )
            display_name = (request.POST.get('display_name') or '').strip()
            password = request.POST.get('password') or ''
            is_active = request.POST.get('is_active') == 'on'
            role_slugs = _posted_role_slugs(request)
            permission_codes = _posted_permissions(request)

            if profile.user_id == request.user.id and not is_active:
                error = 'You cannot deactivate yourself.'
            elif not role_slugs:
                error = 'Select at least one role.'
            elif not permission_codes:
                error = 'Select at least one permission.'
            else:
                if password:
                    try:
                        validate_password(password, profile.user)
                    except ValidationError as exc:
                        error = ' '.join(exc.messages)
                if not error:
                    with transaction.atomic():
                        profile.display_name = display_name
                        profile.is_active = is_active
                        profile.save(update_fields=['display_name', 'is_active'])
                        _apply_display_name(profile.user, display_name)
                        apply_roles_and_permissions(
                            profile, role_slugs, permission_codes
                        )
                        profile.user.is_active = is_active
                        profile.user.is_staff = is_active
                        if not is_active:
                            profile.user.is_superuser = False
                        profile.user.save(
                            update_fields=['is_active', 'is_staff', 'is_superuser']
                        )
                        if password:
                            profile.user.set_password(password)
                            profile.user.save(update_fields=['password'])
                    log_staff_activity(
                        request.user,
                        StaffActivity.Action.TEAM_EDIT,
                        f'Updated {profile.user.username}',
                        username=profile.user.username,
                        roles=role_slugs,
                        permissions=permission_codes,
                        is_active=is_active,
                    )
                    messages.success(request, f'Updated {profile.label()}.')
                    return redirect('kahawa:manage_team')

        elif action == 'toggle_active':
            profile = get_object_or_404(
                StaffProfile, pk=request.POST.get('profile_id')
            )
            if profile.user_id == request.user.id:
                messages.error(request, 'You cannot deactivate yourself.')
            else:
                profile.is_active = not profile.is_active
                profile.save(update_fields=['is_active'])
                profile.user.is_active = profile.is_active
                profile.user.is_staff = profile.is_active
                profile.user.save(update_fields=['is_active', 'is_staff'])
                log_staff_activity(
                    request.user,
                    StaffActivity.Action.TEAM_DEACTIVATE,
                    f'{"Activated" if profile.is_active else "Deactivated"} {profile.user.username}',
                    username=profile.user.username,
                    is_active=profile.is_active,
                )
                messages.success(
                    request,
                    f'{profile.label()} is now {"active" if profile.is_active else "inactive"}.',
                )
            return redirect('kahawa:manage_team')

    import json

    team = (
        StaffProfile.objects.select_related('user')
        .prefetch_related('roles')
        .order_by('user__username')
    )
    staff_roles = list(StaffRole.objects.order_by('sort_order', 'name'))
    role_presets = {r.slug: list(r.default_permissions or []) for r in staff_roles}
    team_payload = [
        {
            'id': m.id,
            'username': m.user.username,
            'display': m.display_name or '',
            'active': m.is_active,
            'self': m.user_id == request.user.id,
            'roles': list(m.roles.values_list('slug', flat=True)),
            'permissions': list(m.permissions or []),
            'role_label': m.role_label(),
        }
        for m in team
    ]
    return render(
        request,
        'staff/manage_team.html',
        _ctx(
            request,
            team=team,
            error=error,
            form_mode=form_mode,
            page='team',
            staff_roles=staff_roles,
            role_presets_json=json.dumps(role_presets),
            team_payload_json=json.dumps(team_payload),
        ),
    )


@admin_required
@require_GET
def manage_team_activity(request, profile_id):
    from .models import StaffActivity

    profile = get_object_or_404(
        StaffProfile.objects.select_related('user').prefetch_related('roles'),
        pk=profile_id,
    )
    activities = (
        StaffActivity.objects.filter(actor=profile.user)
        .order_by('-created_at')[:100]
    )
    return render(
        request,
        'staff/manage_team_activity.html',
        _ctx(
            request,
            page='team',
            member=profile,
            activities=activities,
        ),
    )
