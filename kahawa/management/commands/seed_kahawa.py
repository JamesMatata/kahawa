"""
Seed realistic demo catalog, staff user, and sample orders for Kahawa.

Idempotent — safe to re-run: uses update_or_create throughout.

Usage:
    python manage.py seed_kahawa
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from kahawa.models import CafeTable, Category, GiftCard, Order, OrderItem, Product, StaffProfile

User = get_user_model()

CATEGORIES = [
    {
        'slug': 'hot-brews',
        'name': 'Espresso & Hot Brews',
        'is_featured': True,
    },
    {
        'slug': 'iced-brews',
        'name': 'Cold Brews & Iced',
        'is_featured': True,
    },
    {
        'slug': 'teas',
        'name': 'Kenyan Teas & Chai',
        'is_featured': False,
    },
    {
        'slug': 'pastries',
        'name': 'Pastries & Bakery',
        'is_featured': True,
    },
    {
        'slug': 'bites',
        'name': 'Quick Sandwiches',
        'is_featured': False,
    },
]

PRODUCTS = [
    # Hot Brews
    {
        'category_slug': 'hot-brews',
        'name': 'Kenyan AA Single Origin Pour-over',
        'description': (
            'Bright blackcurrant and citrus notes from Nyeri highlands. '
            'Brewed to order on the V60.'
        ),
        'price': Decimal('400.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1495474472287-4d71bcdd2085'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': False,
    },
    {
        'category_slug': 'hot-brews',
        'name': 'Caramel Vanilla Latte',
        'description': (
            'Double espresso, steamed milk, house caramel, and Madagascar vanilla. '
            'The weekday favourite.'
        ),
        'price': Decimal('380.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1572442388796-11614d95e0ae'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': True,
    },
    {
        'category_slug': 'hot-brews',
        'name': 'Double Shot Espresso',
        'description': (
            'Unapologetic ristretto-style double shot. Dense crema, short finish.'
        ),
        'price': Decimal('250.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1510591509098-f4fdc6d0ff04'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': False,
    },
    {
        'category_slug': 'hot-brews',
        'name': 'Hazelnut Cappuccino',
        'description': (
            'Silky microfoam with roasted hazelnut syrup over a bold espresso base.'
        ),
        'price': Decimal('380.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1534778101976-628585232cfd'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': True,
    },
    # Cold
    {
        'category_slug': 'iced-brews',
        'name': 'Nitro Cold Brew',
        'description': (
            '18-hour steep, nitrogen-infused. Creamy cascade without dairy.'
        ),
        'price': Decimal('450.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1461023058943-07fcbe16d735'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': True,
    },
    {
        'category_slug': 'iced-brews',
        'name': 'Iced Spanish Latte',
        'description': (
            'Espresso, condensed milk, and ice — sweet, strong, and CBD-ready.'
        ),
        'price': Decimal('420.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1517701604599-bb29b565090c'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': False,
    },
    {
        'category_slug': 'iced-brews',
        'name': 'Classic Iced Americano',
        'description': (
            'Double shot over ice with a splash of cold water. Clean and sharp.'
        ),
        'price': Decimal('320.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1511920170033-f8396924c348'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': False,
    },
    # Pastries
    {
        'category_slug': 'pastries',
        'name': 'Cardamom Spiced Mandazi 3pcs',
        'description': (
            'Golden East-African doughnuts dusted with cardamom sugar. Best warm.'
        ),
        'price': Decimal('200.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1555507036-ab1f4038808a'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': False,
    },
    {
        'category_slug': 'pastries',
        'name': 'Pistachio Croissant',
        'description': (
            'Laminated butter croissant filled with pistachio cream and crushed nuts.'
        ),
        'price': Decimal('350.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1509440159596-0249088772ff'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': True,
    },
    {
        'category_slug': 'pastries',
        'name': 'Triple Berry Muffin',
        'description': (
            'Blueberry, raspberry, and strawberry baked into a tender morning muffin.'
        ),
        'price': Decimal('300.00'),
        'image_url': (
            'https://images.unsplash.com/photo-1607958996333-41aef7caefaa'
            '?auto=format&fit=crop&w=1200&q=80'
        ),
        'is_featured': False,
    },
]

SAMPLE_ORDERS = [
    {
        'order_code': 'KHW-SEED1',
        'customer_name': 'Amina Njeri',
        'phone': '+254712345678',
        'order_type': Order.OrderType.PICKUP,
        'delivery_location': '',
        'status': Order.Status.PENDING,
        'payment_status': Order.PaymentStatus.PENDING,
        'items': [
            {
                'product_name': 'Caramel Vanilla Latte',
                'quantity': 1,
                'customization': {
                    'size': 'Large',
                    'milk': 'Oat',
                    'extra_shot': False,
                },
                'unit_extra': Decimal('100.00'),  # Large + Oat
            },
            {
                'product_name': 'Pistachio Croissant',
                'quantity': 1,
                'customization': {},
                'unit_extra': Decimal('0.00'),
            },
        ],
    },
    {
        'order_code': 'KHW-SEED2',
        'customer_name': 'Brian Otieno',
        'phone': '+254722987654',
        'order_type': Order.OrderType.DELIVERY,
        'delivery_location': 'Lonrho House, 3rd floor · Kimathi Street',
        'status': Order.Status.PREPARING,
        'payment_status': Order.PaymentStatus.PAID,
        'items': [
            {
                'product_name': 'Nitro Cold Brew',
                'quantity': 2,
                'customization': {
                    'size': 'Regular',
                    'milk': 'Dairy',
                    'extra_shot': False,
                },
                'unit_extra': Decimal('0.00'),
            },
        ],
    },
    {
        'order_code': 'KHW-SEED3',
        'customer_name': 'Faith Wanjiku',
        'phone': '+254733456789',
        'order_type': Order.OrderType.PICKUP,
        'delivery_location': '',
        'status': Order.Status.READY,
        'payment_status': Order.PaymentStatus.PAID,
        'items': [
            {
                'product_name': 'Hazelnut Cappuccino',
                'quantity': 1,
                'customization': {
                    'size': 'Regular',
                    'milk': 'Almond',
                    'extra_shot': True,
                },
                'unit_extra': Decimal('150.00'),  # Almond + extra shot
            },
            {
                'product_name': 'Cardamom Spiced Mandazi 3pcs',
                'quantity': 1,
                'customization': {},
                'unit_extra': Decimal('0.00'),
            },
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed Kahawa categories, products, staff user, and sample orders (idempotent).'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Seeding Kahawa demo data…'))

        categories = self._seed_categories()
        products = self._seed_products(categories)
        staff = self._seed_staff_user()
        self._seed_tables()
        self._seed_demo_gift_card()
        self._seed_orders(products)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Kahawa seed complete.'))
        self.stdout.write(f'  Categories : {Category.objects.count()}')
        self.stdout.write(f'  Products   : {Product.objects.count()}')
        self.stdout.write(f'  Tables     : {CafeTable.objects.count()}')
        self.stdout.write(f'  Orders     : {Order.objects.filter(order_code__startswith="KHW-SEED").count()} sample')
        self.stdout.write(
            self.style.WARNING(
                f'  Admin login : {staff.username} / kahawa2026!  at /manage/'
            )
        )
        self.stdout.write(
            self.style.WARNING(
                '  Staff login : barista / barista2026!  at /manage/'
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                '  Table QR URLs: /t/t1/ · /t/t2/ · /t/t3/ · /t/t4/'
            )
        )

    def _seed_tables(self) -> None:
        tables = [
            ('t1', 'Window · 2 seats'),
            ('t2', 'Counter · 2 seats'),
            ('t3', 'Booth · 4 seats'),
            ('t4', 'Patio · 4 seats'),
        ]
        for code, label in tables:
            table, created = CafeTable.objects.update_or_create(
                code=code,
                defaults={'label': label, 'is_active': True},
            )
            flag = 'created' if created else 'updated'
            self.stdout.write(f'  [{flag}] table {table.code}')

    def _seed_demo_gift_card(self) -> None:
        from kahawa.models import CustomerProfile

        staff = User.objects.filter(username='staff').first()
        phone = '+254712345678'
        if staff:
            profile, _ = CustomerProfile.objects.get_or_create(user=staff)
            if not profile.phone:
                profile.phone = phone
                profile.save(update_fields=['phone'])
            else:
                phone = profile.phone

        gift, created = GiftCard.objects.update_or_create(
            code='GFT-DEMO01',
            defaults={
                'initial_balance': Decimal('500.00'),
                'balance': Decimal('500.00'),
                'purchaser_phone': phone,
                'payment_status': 'PAID',
                'payment_method': GiftCard.PaymentMethod.COMPLIMENTARY,
                'is_active': True,
                'created_by': staff,
            },
        )
        flag = 'created' if created else 'updated'
        self.stdout.write(f'  [{flag}] gift card {gift.code} (KSh {gift.balance})')

    def _seed_categories(self) -> dict[str, Category]:
        by_slug: dict[str, Category] = {}
        for data in CATEGORIES:
            category, created = Category.objects.update_or_create(
                slug=data['slug'],
                defaults={
                    'name': data['name'],
                    'is_featured': data['is_featured'],
                },
            )
            by_slug[category.slug] = category
            flag = 'created' if created else 'updated'
            self.stdout.write(f'  [{flag}] category {category.slug}')
        return by_slug

    def _seed_products(self, categories: dict[str, Category]) -> dict[str, Product]:
        by_name: dict[str, Product] = {}
        for data in PRODUCTS:
            category = categories[data['category_slug']]
            product, created = Product.objects.update_or_create(
                category=category,
                name=data['name'],
                defaults={
                    'description': data['description'],
                    'price': data['price'],
                    'image_url': data['image_url'],
                    'is_featured': data['is_featured'],
                    'is_available': True,
                    'allow_size': data['category_slug'] in (
                        'hot-brews',
                        'iced-brews',
                        'teas',
                    ),
                    'allow_milk': data['category_slug'] in (
                        'hot-brews',
                        'iced-brews',
                        'teas',
                    ),
                    'allow_extra_shot': data['category_slug'] in (
                        'hot-brews',
                        'iced-brews',
                        'teas',
                    ),
                },
            )
            by_name[product.name] = product
            flag = 'created' if created else 'updated'
            self.stdout.write(f'  [{flag}] product {product.name}')
        return by_name

    def _seed_staff_user(self):
        from kahawa.staff_roles import apply_roles_and_permissions, ensure_system_roles

        ensure_system_roles()
        staff, created = User.objects.update_or_create(
            username='staff',
            defaults={
                'email': 'staff@kahawa.local',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
                'first_name': 'Kahawa',
                'last_name': 'Admin',
            },
        )
        # Always reset password so re-runs restore the known demo credential.
        staff.set_password('kahawa2026!')
        staff.save()
        profile, _ = StaffProfile.objects.update_or_create(
            user=staff,
            defaults={
                'display_name': 'Kahawa Admin',
                'is_active': True,
            },
        )
        apply_roles_and_permissions(profile, ['admin'], None)
        flag = 'created' if created else 'updated'
        self.stdout.write(f'  [{flag}] admin user "{staff.username}"')

        barista, b_created = User.objects.update_or_create(
            username='barista',
            defaults={
                'email': 'barista@kahawa.local',
                'is_staff': True,
                'is_superuser': False,
                'is_active': True,
                'first_name': 'Amina',
                'last_name': 'Barista',
            },
        )
        barista.set_password('barista2026!')
        barista.save()
        b_profile, _ = StaffProfile.objects.update_or_create(
            user=barista,
            defaults={
                'display_name': 'Amina',
                'is_active': True,
                'created_by': staff,
            },
        )
        apply_roles_and_permissions(b_profile, ['barista'], None)
        b_flag = 'created' if b_created else 'updated'
        self.stdout.write(f'  [{b_flag}] staff user "{barista.username}"')
        return staff

    def _seed_orders(self, products: dict[str, Product]) -> None:
        for spec in SAMPLE_ORDERS:
            line_defs = []
            total = Decimal('0.00')
            for line in spec['items']:
                product = products[line['product_name']]
                unit_price = product.price + line['unit_extra']
                qty = line['quantity']
                total += unit_price * qty
                line_defs.append(
                    {
                        'product': product,
                        'quantity': qty,
                        'unit_price': unit_price,
                        'customization': line['customization'],
                    }
                )

            # Delivery fee for seeded delivery orders (matches storefront pricing).
            if spec['order_type'] == Order.OrderType.DELIVERY:
                total += Decimal('100.00')

            order, created = Order.objects.update_or_create(
                order_code=spec['order_code'],
                defaults={
                    'customer_name': spec['customer_name'],
                    'phone': spec['phone'],
                    'order_type': spec['order_type'],
                    'delivery_location': spec['delivery_location'],
                    'status': spec['status'],
                    'payment_status': spec['payment_status'],
                    'total_amount': total,
                },
            )

            # Replace line items so re-runs stay consistent.
            order.items.all().delete()
            OrderItem.objects.bulk_create(
                [
                    OrderItem(
                        order=order,
                        product=line['product'],
                        quantity=line['quantity'],
                        unit_price=line['unit_price'],
                        customization=line['customization'],
                    )
                    for line in line_defs
                ]
            )

            flag = 'created' if created else 'updated'
            self.stdout.write(
                f'  [{flag}] order {order.order_code} ({order.status}) '
                f'— KSh {order.total_amount}'
            )
