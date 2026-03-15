# Generated migration — add ParticipantRelation, remove old settlement models

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('TripApp', '0002_prepayment_rate'),
    ]

    operations = [
        migrations.CreateModel(
            name='ParticipantRelation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('left_for_settled', models.JSONField(default=list)),
                ('all_related_amount', models.JSONField(default=list)),
                ('prepayment_details', models.JSONField(default=dict)),
                ('trip', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='participant_relations',
                    to='TripApp.trip',
                )),
                ('participant_a', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='relations_as_a',
                    to='TripApp.participant',
                )),
                ('participant_b', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='relations_as_b',
                    to='TripApp.participant',
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name='participantrelation',
            constraint=models.UniqueConstraint(
                fields=('trip', 'participant_a', 'participant_b'),
                name='unique_relation_per_trip',
            ),
        ),
        migrations.DeleteModel(
            name='SettlementTripCurrency',
        ),
        migrations.DeleteModel(
            name='SettlementOtherCurrency',
        ),
    ]