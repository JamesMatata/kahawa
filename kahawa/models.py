import secrets

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify

# Avoid ambiguous 0/O and 1/I in public codes
_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


class Category(models.Model):
    name = models.CharField(max_length=50)
    slug = models.SlugField(unique=True)
    is_featured = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)  # KSh
    image_url = models.URLField(max_length=500, blank=True)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    prep_minutes = models.PositiveSmallIntegerField(
        default=8,
        help_text='Typical prep time in minutes for order estimates.',
    )
    allergens = models.CharField(
        max_length=200,
        blank=True,
        help_text='Comma-separated allergens, e.g. milk, gluten, nuts',
    )
    allow_size = models.BooleanField(
        default=False,
        help_text='Offer Regular / Large when adding to the bag.',
    )
    allow_milk = models.BooleanField(
        default=False,
        help_text='Offer dairy, oat, or almond milk.',
    )
    allow_extra_shot = models.BooleanField(
        default=False,
        help_text='Offer an extra espresso shot.',
    )
    tax_type = models.CharField(
        max_length=1,
        default='B',
        help_text='KRA tax code. Menu price already includes this tax.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def has_customization(self) -> bool:
        return bool(self.allow_size or self.allow_milk or self.allow_extra_shot)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def image_src(self) -> str:
        """Prefer uploaded image, then external URL."""
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        return self.image_url or ''


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)
    default_location = models.TextField(blank=True)
    loyalty_points = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f'Profile · {self.user.get_username()}'


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_customer_profile(sender, instance, created, **kwargs):
    if created:
        CustomerProfile.objects.get_or_create(user=instance)


class StaffRole(models.Model):
    """Named permission preset (barista, cashier, …). Staff may hold several."""

    slug = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=60)
    description = models.TextField(blank=True, default='')
    is_system = models.BooleanField(default=True)
    default_permissions = models.JSONField(default=list, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class StaffProfile(models.Model):
    """Cafe team member — separate from customer profile."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_profile',
    )
    display_name = models.CharField(max_length=80, blank=True, default='')
    is_active = models.BooleanField(default=True)
    roles = models.ManyToManyField(
        StaffRole,
        blank=True,
        related_name='members',
    )
    # Effective capabilities after role merge + admin edits
    permissions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_created',
    )

    class Meta:
        ordering = ['user__username']

    def __str__(self):
        return f'{self.user.get_username()} · {self.role_label()}'

    def label(self) -> str:
        return self.display_name or self.user.get_full_name() or self.user.get_username()

    def role_label(self) -> str:
        names = list(self.roles.values_list('name', flat=True)[:3])
        if not names:
            return 'Staff'
        return ' · '.join(names)

    def has_perm(self, code: str) -> bool:
        if not self.is_active:
            return False
        return code in (self.permissions or [])

    @property
    def is_admin(self) -> bool:
        return self.has_perm('team.manage')

class StaffActivity(models.Model):
    """Audit log of cafe team actions for admin review."""

    class Action(models.TextChoices):
        LOGIN = 'LOGIN', 'Signed in'
        LOGOUT = 'LOGOUT', 'Signed out'
        ORDER_STATUS = 'ORDER_STATUS', 'Updated order'
        PRODUCT_TOGGLE = 'PRODUCT_TOGGLE', 'Toggled product'
        PRODUCT_EDIT = 'PRODUCT_EDIT', 'Edited product'
        TEAM_CREATE = 'TEAM_CREATE', 'Created team member'
        TEAM_EDIT = 'TEAM_EDIT', 'Edited team member'
        TEAM_DEACTIVATE = 'TEAM_DEACTIVATE', 'Changed team status'
        GIFT_ISSUE = 'GIFT_ISSUE', 'Issued gift card'
        OTHER = 'OTHER', 'Activity'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_activities',
    )
    action = models.CharField(max_length=30, choices=Action.choices, default=Action.OTHER)
    summary = models.CharField(max_length=255)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'staff activities'

    def __str__(self):
        return f'{self.actor} · {self.action} · {self.created_at:%Y-%m-%d %H:%M}'


class CafeTable(models.Model):
    code = models.SlugField(max_length=20, unique=True)
    label = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} · {self.label}'


class GiftCard(models.Model):
    class PaymentMethod(models.TextChoices):
        NONE = '', '—'
        CASH = 'CASH', 'Cash'
        MPESA = 'MPESA', 'M-Pesa'
        COMPLIMENTARY = 'GIFT', 'Complimentary'

    code = models.CharField(max_length=16, unique=True)
    initial_balance = models.DecimalField(max_digits=10, decimal_places=2)
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    purchaser_phone = models.CharField(max_length=20, blank=True, default='')
    recipient_phone = models.CharField(max_length=20, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gift_cards_created',
    )
    mpesa_checkout_request_id = models.CharField(max_length=100, blank=True, default='')
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('PAID', 'Paid'),
            ('FAILED', 'Failed'),
        ],
        default='PENDING',
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        blank=True,
        default='',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    @property
    def needs_payment(self) -> bool:
        return self.payment_status != 'PAID'

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} · KSh {self.balance}'

    @staticmethod
    def generate_code():
        suffix = ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        return f'GFT-{suffix}'

    def save(self, *args, **kwargs):
        if not self.code:
            code = self.generate_code()
            while GiftCard.objects.filter(code=code).exists():
                code = self.generate_code()
            self.code = code
        super().save(*args, **kwargs)


class Order(models.Model):
    class OrderType(models.TextChoices):
        PICKUP = 'PICKUP', 'Pickup'
        DELIVERY = 'DELIVERY', 'Delivery'
        DINE_IN = 'DINE_IN', 'Dine in'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PREPARING = 'PREPARING', 'Preparing'
        READY = 'READY', 'Ready for Pickup / Out for Delivery'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    class Source(models.TextChoices):
        STOREFRONT = 'STOREFRONT', 'Storefront'
        COUNTER = 'COUNTER', 'Counter'

    class PaymentMethod(models.TextChoices):
        NONE = '', '—'
        CASH = 'CASH', 'Cash'
        MPESA = 'MPESA', 'M-Pesa'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders_created',
    )
    table = models.ForeignKey(
        CafeTable,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    order_code = models.CharField(max_length=16, unique=True)
    customer_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True, default='')
    order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
        default=OrderType.PICKUP,
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.STOREFRONT,
    )
    delivery_location = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        blank=True,
        default='',
    )
    # True = hold off Live ops until PAID (storefront/counter M-Pesa checkout).
    # False = pay-later / already released to kitchen.
    prep_after_payment = models.BooleanField(default=False)
    mpesa_checkout_request_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )
    mpesa_receipt = models.CharField(max_length=100, blank=True, default='')
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True, default='')
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    points_redeemed = models.PositiveIntegerField(default=0)
    points_earned = models.PositiveIntegerField(default=0)
    gift_card = models.ForeignKey(
        GiftCard,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    gift_card_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash_tendered = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cash_change = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.order_code

    @staticmethod
    def generate_order_code():
        """Return a hard-to-guess code like KHW-7K3M9PQ2."""
        suffix = ''.join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        return f'KHW-{suffix}'

    def save(self, *args, **kwargs):
        if not self.order_code:
            code = self.generate_order_code()
            while Order.objects.filter(order_code=code).exists():
                code = self.generate_order_code()
            self.order_code = code
        super().save(*args, **kwargs)


class Package(models.Model):
    """Fixed-price combo. Live only while its schedule says so."""

    class ScheduleMode(models.TextChoices):
        ALWAYS = 'ALWAYS', 'Every day'
        UNTIL = 'UNTIL', 'Until a date and time'
        WEEKLY = 'WEEKLY', 'Selected weekdays'

    class ImageRatio(models.TextChoices):
        SQUARE = '1:1', 'Square'
        STANDARD = '4:3', 'Standard'
        WIDE = '16:9', 'Wide'

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    image_url = models.URLField(max_length=500, blank=True)
    image = models.ImageField(upload_to='packages/', blank=True, null=True)
    image_ratio = models.CharField(
        max_length=8,
        choices=ImageRatio.choices,
        default=ImageRatio.WIDE,
    )
    tax_type = models.CharField(
        max_length=1,
        default='B',
        help_text='KRA tax code for the package price.',
    )
    is_active = models.BooleanField(default=True)
    schedule_mode = models.CharField(
        max_length=20,
        choices=ScheduleMode.choices,
        default=ScheduleMode.ALWAYS,
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    weekdays = models.JSONField(default=list, blank=True)
    window_start = models.TimeField(null=True, blank=True)
    window_end = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def image_src(self) -> str:
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        return self.image_url or ''

    @property
    def image_aspect(self) -> str:
        return {
            self.ImageRatio.SQUARE: '1 / 1',
            self.ImageRatio.STANDARD: '4 / 3',
            self.ImageRatio.WIDE: '16 / 9',
        }.get(self.image_ratio, '16 / 9')

    def is_live(self, at=None) -> bool:
        from django.utils import timezone

        if not self.is_active:
            return False
        now = timezone.localtime(at or timezone.now())
        start = timezone.localtime(self.starts_at) if self.starts_at else None
        end = timezone.localtime(self.ends_at) if self.ends_at else None
        if start and now < start:
            return False
        if self.schedule_mode == self.ScheduleMode.UNTIL:
            return bool(end and now < end)
        if end and now >= end:
            return False
        if self.schedule_mode == self.ScheduleMode.WEEKLY:
            days = [int(d) for d in (self.weekdays or [])]
            if now.weekday() not in days:
                return False
            if self.window_start and self.window_end:
                current = now.time().replace(microsecond=0)
                if self.window_start <= self.window_end:
                    if not (self.window_start <= current < self.window_end):
                        return False
                elif not (current >= self.window_start or current < self.window_end):
                    return False
        return True

    @property
    def compare_at(self):
        from decimal import Decimal

        total = Decimal('0')
        for row in self.items.select_related('product'):
            total += Decimal(row.product.price) * row.quantity
        return total


class PackageItem(models.Model):
    package = models.ForeignKey(
        Package,
        on_delete=models.CASCADE,
        related_name='items',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='package_items',
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.quantity}× {self.product.name}'


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    package = models.ForeignKey(
        'Package',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_items',
    )
    item_name = models.CharField(max_length=120, blank=True, default='')
    tax_type = models.CharField(max_length=1, default='B')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    customization = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.quantity}× {self.display_name}'

    @property
    def display_name(self) -> str:
        if self.item_name:
            return self.item_name
        if self.product_id and self.product:
            return self.product.name
        return 'Item'

    @property
    def line_total(self):
        return self.unit_price * self.quantity
