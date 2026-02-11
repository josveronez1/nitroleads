# Onboarding fields on UserProfile

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lead_extractor', '0012_add_searchlead'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='onboarding_completed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='onboarding_role',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='onboarding_pain_points',
            field=models.JSONField(default=list),
        ),
    ]
