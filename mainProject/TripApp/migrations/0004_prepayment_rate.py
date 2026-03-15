import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('TripApp', '0003_participantrelation_remove_old_settlements'),
    ]

    operations = [
        migrations.CreateModel(
            name='SettlementHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('settlement_type', models.CharField(
                    choices=[
                        ('MANUAL_BY_AMOUNT', 'Manual By Amount'),
                        ('MANUAL_BY_COSTS', 'Manual By Costs'),
                        ('AUTO_PREPAYMENT', 'Auto Prepayment'),
                        ('AUTO_CROSS_SETTLE', 'Auto Cross Settle'),
                    ],
                    max_length=20,
                )),
                ('amount_in_settlement_currency', models.DecimalField(decimal_places=2, max_digits=10)),
                ('settlement_currency', models.CharField(max_length=5)),
                ('amount_in_trip_currency', models.DecimalField(decimal_places=2, max_digits=10)),
                ('related_expenses', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('trip', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='settlement_history',
                    to='TripApp.trip',
                )),
                ('participant_a', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='settlement_history_as_a',
                    to='TripApp.participant',
                )),
                ('participant_b', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='settlement_history_as_b',
                    to='TripApp.participant',
                )),
                ('actor_participant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='settlement_actions',
                    to='TripApp.participant',
                )),
            ],
        ),
    ]