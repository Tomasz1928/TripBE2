from datetime import datetime, timezone
from decimal import Decimal
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant, Expense, Split


async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """
    Placeholder: returns 1:1 rate.
    TODO: fetch real rate from external API (e.g. exchangerate-api, frankfurter, etc.)
    """
    if from_currency.upper() == to_currency.upper():
        return Decimal("1.000000")

    # TODO: implement real exchange rate fetching
    return Decimal("1.000000")


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _is_settlement(payer_id: int, participant_id: int) -> bool:
    return payer_id == participant_id


async def add_expense(request: HttpRequest, data: dict) -> dict:
    trip_id = data["trip_id"]
    trip = await sync_to_async(Trip.objects.select_related("trip_owner").get)(trip_id=trip_id)

    # Verify payer exists and belongs to this trip
    payer = await sync_to_async(Participant.objects.get)(
        participant_id=data["payer_id"], trip=trip
    )

    expense_currency = data["currency"].strip().upper()
    trip_currency = trip.default_currency.upper()

    rate = await get_exchange_rate(expense_currency, trip_currency)

    amount_in_expense_currency = _to_decimal(data["amount"])
    amount_in_trip_currency = (amount_in_expense_currency * rate).quantize(Decimal("0.01"))

    created_at = datetime.fromtimestamp(data["date"] / 1000, tz=timezone.utc)

    expense = await sync_to_async(Expense.objects.create)(
        trip=trip,
        title=data["name"].strip(),
        description=data.get("description", "").strip(),
        category=data["category_id"],
        expense_currency=expense_currency,
        amount_in_expenses_currency=amount_in_expense_currency,
        amount_in_trip_currency=amount_in_trip_currency,
        rate=rate,
        payer=payer,
        created_at=created_at,
    )

    splits = []
    for share in data["shared_with"]:
        participant = await sync_to_async(Participant.objects.get)(
            participant_id=share["participant_id"], trip=trip
        )

        # Sum up split values per currency type
        split_amount_cost = Decimal("0.00")
        split_amount_trip = Decimal("0.00")

        for money in share["split_value"]:
            amount = _to_decimal(money["amount"])
            money_currency = money["currency"].strip().upper()
            is_main = (money_currency == trip_currency)

            if is_main:
                split_amount_trip += amount
                if rate != Decimal("0"):
                    split_amount_cost += (amount / rate).quantize(Decimal("0.01"))
            else:
                split_amount_cost += amount
                split_amount_trip += (amount * rate).quantize(Decimal("0.01"))

        is_settled = _is_settlement(payer.participant_id, participant.participant_id)

        split = await sync_to_async(Split.objects.create)(
            participant=participant,
            expense=expense,
            is_settlement=is_settled,
            amount_in_cost_currency=split_amount_cost,
            amount_in_trip_currency=split_amount_trip,
            left_to_settlement_amount_in_cost_currency=Decimal("0.00") if is_settled else split_amount_cost,
            left_to_settlement_amount_in_trip_currency=Decimal("0.00") if is_settled else split_amount_trip,
        )

        splits.append({
            "participant_id": participant.participant_id,
            "participant_nickname": participant.nickname,
            "amount_in_cost_currency": float(split_amount_cost),
            "amount_in_trip_currency": float(split_amount_trip),
        })

    return {
        "success": True,
        "message": "Expense added successfully.",
        "expense": expense,
        "splits": splits,
    }