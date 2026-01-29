# Generated manually for Kiwify integration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lead_extractor', '0009_leadaccess_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='credittransaction',
            name='kiwify_sale_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='credittransaction',
            name='payment_gateway',
            field=models.CharField(
                choices=[('kiwify', 'Kiwify'), ('stripe', 'Stripe')],
                default='kiwify',
                max_length=20,
            ),
        ),
    ]
