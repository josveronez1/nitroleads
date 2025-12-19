# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('lead_extractor', '0003_viperrequestqueue'),
    ]

    operations = [
        migrations.AddField(
            model_name='viperrequestqueue',
            name='lead',
            field=models.ForeignKey(
                blank=True,
                help_text='Lead associado a esta requisição (opcional)',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='viper_queue_requests',
                to='lead_extractor.lead'
            ),
        ),
    ]

