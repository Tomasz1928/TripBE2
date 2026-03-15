from django.db import models
from django.contrib.auth.models import User
from django.db.models import Q


class Trip(models.Model):
    trip_id = models.AutoField(primary_key=True)
    trip_owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_trips")
    title = models.CharField(max_length=40)
    description = models.TextField(max_length=200, blank=True, default="")
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    default_currency = models.CharField(max_length=5)


class Participant(models.Model):
    access_code = models.CharField(max_length=8, db_index=True, null=True, blank=True)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    nickname = models.CharField(max_length=25)
    is_placeholder = models.BooleanField(default=True)
    participant_id = models.AutoField(primary_key=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["access_code"],
                condition=Q(user__isnull=True),
                name="unique_join_code_when_user_null"
            ),
            models.UniqueConstraint(
                fields=["trip", "user"],
                condition=Q(user__isnull=False),
                name="unique_user_per_trip"
            ),
        ]


class Expense(models.Model):
    expense_id = models.AutoField(primary_key=True)
    created_at = models.DateTimeField()
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    title = models.CharField(max_length=30)
    description = models.TextField(max_length=250, blank=True, default="")
    category = models.IntegerField()
    expense_currency = models.CharField(max_length=5)
    amount_in_expenses_currency = models.DecimalField(max_digits=10, decimal_places=2)
    amount_in_trip_currency = models.DecimalField(max_digits=10, decimal_places=2)
    rate = models.DecimalField(max_digits=12, decimal_places=6)
    payer = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="paid_expenses")


class Split(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="splits")
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="splits")
    is_settlement = models.BooleanField(default=False)
    amount_in_cost_currency = models.DecimalField(max_digits=10, decimal_places=2)
    amount_in_trip_currency = models.DecimalField(max_digits=10, decimal_places=2)
    left_to_settlement_amount_in_cost_currency = models.DecimalField(max_digits=10, decimal_places=2)
    left_to_settlement_amount_in_trip_currency = models.DecimalField(max_digits=10, decimal_places=2)


class Prepayment(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    from_participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="prepayments_from")
    to_participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="prepayments_to")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_left = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=5)
    rate = models.DecimalField(max_digits=12, decimal_places=6, default=1)
    created_date = models.DateTimeField(auto_now_add=True)


class ParticipantRelation(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="participant_relations")
    participant_a = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="relations_as_a"
    )
    participant_b = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="relations_as_b"
    )

    left_for_settled = models.JSONField(default=list)
    all_related_amount = models.JSONField(default=list)
    prepayment_details = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["trip", "participant_a", "participant_b"],
                name="unique_relation_per_trip"
            ),
        ]