from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kahawa', '0010_product_image'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='order_code',
            field=models.CharField(max_length=16, unique=True),
        ),
        migrations.AddField(
            model_name='order',
            name='prep_after_payment',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='giftcard',
            name='code',
            field=models.CharField(max_length=16, unique=True),
        ),
    ]
