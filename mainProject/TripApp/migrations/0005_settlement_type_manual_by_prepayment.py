from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('TripApp', '0004_prepayment_rate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='settlementhistory',
            name='settlement_type',
            field=models.CharField(
                choices=[
                    ('MANUAL_BY_AMOUNT', 'Manual By Amount'),
                    ('MANUAL_BY_COSTS', 'Manual By Costs'),
                    ('MANUAL_BY_PREPAYMENT', 'Manual By Prepayment'),
                    ('AUTO_PREPAYMENT', 'Auto Prepayment'),
                    ('AUTO_CROSS_SETTLE', 'Auto Cross Settle'),
                ],
                max_length=20,
            ),
        ),
    ]