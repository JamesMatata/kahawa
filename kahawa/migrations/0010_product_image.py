from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kahawa', '0009_giftcard_payment_method'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='products/'),
        ),
    ]
