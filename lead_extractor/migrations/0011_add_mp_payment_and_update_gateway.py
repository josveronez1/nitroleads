# Generated for Mercado Pago integration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lead_extractor', '0010_add_kiwify_credit_transaction_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='credittransaction',
            name='mp_payment_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='credittransaction',
            name='payment_gateway',
            field=models.CharField(
                choices=[
                    ('mercadopago', 'Mercado Pago'),
                    ('kiwify', 'Kiwify'),
                    ('stripe', 'Stripe'),
                ],
                default='mercadopago',
                max_length=20,
            ),
        ),
    ]
