from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('TripApp', '0005_settlement_type_manual_by_prepayment'),
    ]

    operations = [
        migrations.AddField(
            model_name='split',
            name='settlement_breakdown',
            field=models.JSONField(default=list),
        ),
    ]