def cart(request):
    """Expose cart item count from the session for the base navbar badge."""
    cart_data = request.session.get('cart', {})
    if isinstance(cart_data, dict):
        cart_count = sum(int(qty) for qty in cart_data.values())
    else:
        cart_count = 0
    return {'cart_count': cart_count}


def cafe(request):
    """Cafe contact / trust details for footer and legal pages."""
    from django.conf import settings

    return {
        'cafe': {
            'name': settings.CAFE_NAME,
            'address': settings.CAFE_ADDRESS,
            'hours_weekday': settings.CAFE_HOURS_WEEKDAY,
            'hours_weekend': settings.CAFE_HOURS_WEEKEND,
            'phone': settings.CAFE_PHONE,
            'phone_tel': settings.CAFE_PHONE_TEL,
            'whatsapp': settings.CAFE_WHATSAPP,
            'maps_url': settings.CAFE_MAPS_URL,
            'prep_pickup_min': settings.CAFE_PREP_PICKUP_MIN,
            'prep_delivery_min': settings.CAFE_PREP_DELIVERY_MIN,
        }
    }
