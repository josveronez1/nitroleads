# SocioCpfEnrichment: dados de CPF por usuário (telefones/emails dos sócios)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('lead_extractor', '0013_onboarding_userprofile'),
    ]

    operations = [
        migrations.CreateModel(
            name='SocioCpfEnrichment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('socio_cpf', models.CharField(db_index=True, max_length=14)),
                ('cpf_data', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('lead', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='socio_cpf_enrichments', to='lead_extractor.lead')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='socio_cpf_enrichments', to='lead_extractor.userprofile')),
            ],
            options={
                'unique_together': {('user', 'lead', 'socio_cpf')},
            },
        ),
        migrations.AddIndex(
            model_name='sociocpfenrichment',
            index=models.Index(fields=['user', 'lead'], name='lead_extrac_user_id_7a8b9c_idx'),
        ),
    ]
