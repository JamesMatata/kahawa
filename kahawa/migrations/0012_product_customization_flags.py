from django.db import migrations, models

DRINK_SLUGS = {'hot-brews', 'iced-brews', 'teas'}
DRINK_WORDS = ('brew', 'tea', 'coffee', 'chai', 'latte', 'espresso', 'drink')


def enable_drink_options(apps, schema_editor):
    Product = apps.get_model('kahawa', 'Product')
    for product in Product.objects.select_related('category'):
        slug = ''
        name = ''
        if product.category_id:
            slug = (product.category.slug or '').lower()
            name = (product.category.name or '').lower()
        drink = slug in DRINK_SLUGS or any(word in name for word in DRINK_WORDS)
        if not drink:
            continue
        product.allow_size = True
        product.allow_milk = True
        product.allow_extra_shot = True
        product.save(
            update_fields=['allow_size', 'allow_milk', 'allow_extra_shot']
        )


class Migration(migrations.Migration):

    dependencies = [
        ('kahawa', '0011_order_codes_and_prep_hold'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='allow_size',
            field=models.BooleanField(
                default=False,
                help_text='Offer Regular / Large when adding to the bag.',
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='allow_milk',
            field=models.BooleanField(
                default=False,
                help_text='Offer dairy, oat, or almond milk.',
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='allow_extra_shot',
            field=models.BooleanField(
                default=False,
                help_text='Offer an extra espresso shot.',
            ),
        ),
        migrations.RunPython(enable_drink_options, migrations.RunPython.noop),
    ]
