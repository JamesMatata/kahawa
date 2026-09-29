from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kahawa', '0008_order_pay_later_counter'),
    ]

    operations = [
        migrations.AddField(
            model_name='giftcard',
            name='payment_method',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', '—'),
                    ('CASH', 'Cash'),
                    ('MPESA', 'M-Pesa'),
                    ('GIFT', 'Complimentary'),
                ],
                default='',
                max_length=20,
            ),
        ),
    ]
