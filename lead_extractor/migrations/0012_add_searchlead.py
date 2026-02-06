# Generated for SearchLead junction table

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('lead_extractor', '0011_add_mp_payment_and_update_gateway'),
    ]

    operations = [
        migrations.CreateModel(
            name='SearchLead',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lead', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='search_leads', to='lead_extractor.lead')),
                ('search', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='search_leads', to='lead_extractor.search')),
            ],
            options={
                'unique_together': {('search', 'lead')},
            },
        ),
        migrations.AddIndex(
            model_name='searchlead',
            index=models.Index(fields=['search'], name='lead_extrac_search__a5b4c3_idx'),
        ),
        migrations.AddIndex(
            model_name='searchlead',
            index=models.Index(fields=['lead'], name='lead_extrac_lead_id_d4e5f6_idx'),
        ),
    ]
