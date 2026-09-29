from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kahawa', '0015_cash_tender'),
    ]

    operations = [
        migrations.AddField(
            model_name='package',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='packages/'),
        ),
        migrations.AddField(
            model_name='package',
            name='image_ratio',
            field=models.CharField(
                choices=[('1:1', 'Square'), ('4:3', 'Standard'), ('16:9', 'Wide')],
                default='16:9',
                max_length=8,
            ),
        ),
    ]
