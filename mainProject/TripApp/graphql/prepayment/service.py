from decimal import Decimal
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant, Prepayment
from TripApp.services.reconciliation import apply_prepayment_to_splits
from ..settlement.service import recalculate_settlements
from TripApp.services.delta_builder import build_prepayment_delta
from TripApp.services.broadcast import broadcast_delta
from ..expense.service import get_exchange_rate

VALID_DIRECTIONS = {"TO_ME", "FROM_ME"}


async def add_prepayment(
    request: HttpRequest,
    trip_id: int,
    participant_id: int,
    amount: float,
    currency: str,
    direction: str,
) -> dict:
    currency = currency.strip().upper()
    direction = direction.strip().upper()
    amount_dec = Decimal(str(amount))

    if amount_dec <= Decimal("0"):
        return {"success": False, "message": "Amount must be positive."}

    if not currency:
        return {"success": False, "message": "Currency is required."}

    if direction not in VALID_DIRECTIONS:
        return {"success": False, "message": "Direction must be TO_ME or FROM_ME."}

    trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)
    trip_currency = trip.default_currency.upper()

    user = await sync_to_async(lambda: request.user)()
    try:
        my_participant = await sync_to_async(Participant.objects.get)(
            trip=trip, user=user
        )
    except Participant.DoesNotExist:
        return {"success": False, "message": "You are not a participant in this trip."}

    try:
        other_participant = await sync_to_async(Participant.objects.get)(
            participant_id=participant_id, trip=trip
        )
    except Participant.DoesNotExist:
        return {"success": False, "message": "Participant not found in this trip."}

    if my_participant.participant_id == other_participant.participant_id:
        return {"success": False, "message": "Cannot create a prepayment to yourself."}

    if direction == "FROM_ME":
        from_participant = my_participant
        to_participant = other_participant
    else:
        from_participant = other_participant
        to_participant = my_participant

    if currency != trip_currency:
        has_expenses_in_currency = await sync_to_async(
            lambda: Participant.objects.filter(
                trip=trip
            ).exists() and Trip.objects.filter(
                trip_id=trip_id,
                expense__expense_currency__iexact=currency,
            ).exists()
        )()
        if not has_expenses_in_currency:
            return {
                "success": False,
                "message": f"No expenses in {currency} for this trip. "
                           f"Prepayment must be in trip currency ({trip_currency}) "
                           f"or a currency used in existing expenses.",
            }

    rate = await get_exchange_rate(currency, trip_currency)

    prepayment = await sync_to_async(Prepayment.objects.create)(
        trip=trip,
        from_participant=from_participant,
        to_participant=to_participant,
        amount=amount_dec,
        amount_left=amount_dec,
        currency=currency,
        rate=rate,
    )

    await apply_prepayment_to_splits(prepayment, trip)
    await recalculate_settlements(trip)

    # Broadcast delta
    delta = await build_prepayment_delta(trip)
    await broadcast_delta(trip.trip_id, delta)

    return {"success": True, "message": "Prepayment added and reconciled."}