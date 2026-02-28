"""
Settlement service:
  - recalculate_settlements: rebuild who-owes-whom summaries
  - settle_by_amount: FIFO settlement by value, leftover → Prepayment
  - settle_by_costs: mark specific splits as fully settled
"""

from collections import defaultdict
from decimal import Decimal
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.services.exchange import get_exchange_rate
from TripApp.models import (
    Trip, Split, Expense, Participant, Prepayment,
    SettlementTripCurrency, SettlementOtherCurrency,
)

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Recalculate settlement summaries
# ---------------------------------------------------------------------------

async def recalculate_settlements(trip: Trip) -> None:
    """
    Rebuild all Settlement records for a trip from scratch.
    Considers both unsettled splits AND unused prepayments.

    SettlementTripCurrency: everything converted to trip currency
    SettlementOtherCurrency: everything in original currency (including trip currency)
    """
    trip_currency = trip.default_currency.upper()

    splits = await sync_to_async(
        lambda: list(
            Split.objects.filter(
                expense__trip=trip,
                is_settlement=False,
            ).select_related("expense", "participant")
        )
    )()

    prepayments = await sync_to_async(
        lambda: list(
            Prepayment.objects.filter(
                trip=trip,
                amount_left__gt=ZERO,
            )
        )
    )()

    trip_debts: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    other_debts: dict[tuple[int, int, str], Decimal] = defaultdict(lambda: ZERO)

    for split in splits:
        left_trip = split.left_to_settlement_amount_in_trip_currency
        left_cost = split.left_to_settlement_amount_in_cost_currency

        if left_trip <= ZERO and left_cost <= ZERO:
            continue

        from_id = split.participant_id
        to_id = split.expense.payer_id

        if from_id == to_id:
            continue

        # SettlementTripCurrency — always in trip currency
        if left_trip > ZERO:
            trip_debts[(from_id, to_id)] += left_trip

        # SettlementOtherCurrency — in original currency (ALL currencies including trip)
        expense_currency = split.expense.expense_currency.upper()
        if expense_currency == trip_currency:
            # Trip currency expense → use trip amount
            if left_trip > ZERO:
                other_debts[(from_id, to_id, trip_currency)] += left_trip
        else:
            # Foreign currency expense → use cost amount
            if left_cost > ZERO:
                other_debts[(from_id, to_id, expense_currency)] += left_cost

    # Prepayments with remaining balance create reverse debts
    for prep in prepayments:
        prep_currency = prep.currency.upper()
        from_id = prep.to_participant_id
        to_id = prep.from_participant_id

        if from_id == to_id:
            continue

        # SettlementTripCurrency — converted via rate
        amount_in_trip = (prep.amount_left * prep.rate).quantize(Decimal("0.01"))
        trip_debts[(from_id, to_id)] += amount_in_trip

        # SettlementOtherCurrency — in original currency
        other_debts[(from_id, to_id, prep_currency)] += prep.amount_left

    # Net out trip currency debts
    netted_trip: dict[tuple[int, int], Decimal] = {}
    processed = set()

    for (a, b), amount in trip_debts.items():
        if (a, b) in processed:
            continue
        reverse = trip_debts.get((b, a), ZERO)
        net = amount - reverse
        processed.add((a, b))
        processed.add((b, a))

        if net > ZERO:
            netted_trip[(a, b)] = net.quantize(Decimal("0.01"))
        elif net < ZERO:
            netted_trip[(b, a)] = (-net).quantize(Decimal("0.01"))

    # Net out other currency debts (per currency)
    netted_other: dict[tuple[int, int, str], Decimal] = {}
    processed_other = set()

    for (a, b, curr), amount in other_debts.items():
        key = (a, b, curr)
        if key in processed_other:
            continue
        reverse = other_debts.get((b, a, curr), ZERO)
        net = amount - reverse
        processed_other.add((a, b, curr))
        processed_other.add((b, a, curr))

        if net > ZERO:
            netted_other[(a, b, curr)] = net.quantize(Decimal("0.01"))
        elif net < ZERO:
            netted_other[(b, a, curr)] = (-net).quantize(Decimal("0.01"))

    # Persist
    await sync_to_async(SettlementTripCurrency.objects.filter(trip=trip).delete)()
    await sync_to_async(SettlementOtherCurrency.objects.filter(trip=trip).delete)()

    for (from_id, to_id), amount in netted_trip.items():
        await sync_to_async(SettlementTripCurrency.objects.create)(
            trip=trip,
            from_participant_id=from_id,
            to_participant_id=to_id,
            amount=amount,
        )

    for (from_id, to_id, currency), amount in netted_other.items():
        await sync_to_async(SettlementOtherCurrency.objects.create)(
            trip=trip,
            from_participant_id=from_id,
            to_participant_id=to_id,
            amount=amount,
            currency=currency,
        )


# ---------------------------------------------------------------------------
# Settle by amount
# ---------------------------------------------------------------------------

async def settle_by_amount(
    request: HttpRequest,
    trip_id: int,
    from_user_id: int,
    to_user_id: int,
    amount: float,
    currency: str,
    is_main_currency: bool,
) -> dict:
    from TripApp.services.delta_builder import build_settlement_changed_delta
    from TripApp.services.broadcast import broadcast_delta

    currency = currency.strip().upper()
    amount_dec = Decimal(str(amount))

    if amount_dec <= ZERO:
        return {"success": False, "message": "Amount must be positive."}

    trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)
    trip_currency = trip.default_currency.upper()

    try:
        from_participant = await sync_to_async(Participant.objects.get)(
            participant_id=from_user_id, trip=trip
        )
    except Participant.DoesNotExist:
        return {"success": False, "message": "From participant not found in this trip."}

    try:
        to_participant = await sync_to_async(Participant.objects.get)(
            participant_id=to_user_id, trip=trip
        )
    except Participant.DoesNotExist:
        return {"success": False, "message": "To participant not found in this trip."}

    if from_participant.participant_id == to_participant.participant_id:
        return {"success": False, "message": "Cannot settle with yourself."}

    user = await sync_to_async(lambda: request.user)()
    caller_participant = await sync_to_async(
        lambda: Participant.objects.filter(trip=trip, user=user).first()
    )()

    if not caller_participant:
        return {"success": False, "message": "You are not a participant in this trip."}

    if caller_participant.participant_id not in (
        from_participant.participant_id,
        to_participant.participant_id,
    ):
        return {"success": False, "message": "You can only settle debts you are involved in."}

    base_qs = Split.objects.filter(
        participant_id=from_participant.participant_id,
        expense__payer_id=to_participant.participant_id,
        expense__trip=trip,
        is_settlement=False,
    ).select_related("expense").order_by("expense__created_at")

    if not is_main_currency:
        base_qs = base_qs.filter(expense__expense_currency__iexact=currency)

    if is_main_currency:
        base_qs = base_qs.filter(left_to_settlement_amount_in_trip_currency__gt=ZERO)
    else:
        base_qs = base_qs.filter(left_to_settlement_amount_in_cost_currency__gt=ZERO)

    splits = await sync_to_async(lambda: list(base_qs))()

    remaining = amount_dec

    for split in splits:
        if remaining <= ZERO:
            break

        expense = split.expense
        rate = expense.rate

        if is_main_currency:
            left = split.left_to_settlement_amount_in_trip_currency
            settleable_trip = min(remaining, left)

            split.left_to_settlement_amount_in_trip_currency -= settleable_trip
            remaining -= settleable_trip

            if rate and rate != ZERO:
                settleable_cost = (settleable_trip / rate).quantize(Decimal("0.01"))
            else:
                settleable_cost = settleable_trip

            split.left_to_settlement_amount_in_cost_currency = max(
                ZERO,
                split.left_to_settlement_amount_in_cost_currency - settleable_cost,
            )
        else:
            left = split.left_to_settlement_amount_in_cost_currency
            settleable_cost = min(remaining, left)

            split.left_to_settlement_amount_in_cost_currency -= settleable_cost
            remaining -= settleable_cost

            settleable_trip = (settleable_cost * rate).quantize(Decimal("0.01"))
            split.left_to_settlement_amount_in_trip_currency = max(
                ZERO,
                split.left_to_settlement_amount_in_trip_currency - settleable_trip,
            )

        split.is_settlement = (
            split.left_to_settlement_amount_in_trip_currency <= ZERO
            and split.left_to_settlement_amount_in_cost_currency <= ZERO
        )
        await sync_to_async(split.save)()

    # Leftover → Prepayment
    if remaining > ZERO:
        prep_currency = trip_currency if is_main_currency else currency
        if is_main_currency:
            prep_rate = Decimal("1.000000")
        else:
            prep_rate = await get_exchange_rate(currency, trip_currency)
        await sync_to_async(Prepayment.objects.create)(
            trip=trip,
            from_participant=from_participant,
            to_participant=to_participant,
            amount=remaining,
            amount_left=remaining,
            currency=prep_currency,
            rate=prep_rate,
        )

    await recalculate_settlements(trip)

    settled_amount = amount_dec - remaining

    # Broadcast delta
    delta = await build_settlement_changed_delta(trip)
    await broadcast_delta(trip.trip_id, delta)

    return {
        "success": True,
        "message": (
            f"Settled {settled_amount} {currency}."
            + (f" Leftover {remaining} {currency} saved as prepayment." if remaining > ZERO else "")
        ),
    }


# ---------------------------------------------------------------------------
# Settle by costs
# ---------------------------------------------------------------------------

async def settle_by_costs(
    request: HttpRequest,
    trip_id: int,
    items: list[dict],
) -> dict:
    from TripApp.services.delta_builder import build_settlement_changed_delta
    from TripApp.services.broadcast import broadcast_delta

    if not items:
        return {"success": False, "message": "No items provided."}

    trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)

    user = await sync_to_async(lambda: request.user)()
    caller_participant = await sync_to_async(
        lambda: Participant.objects.filter(trip=trip, user=user).first()
    )()

    if not caller_participant:
        return {"success": False, "message": "You are not a participant in this trip."}

    caller_id = caller_participant.participant_id
    settled_count = 0

    for item in items:
        expense_id = item["expense_id"]
        participant_id = item["participant_id"]

        try:
            expense = await sync_to_async(
                Expense.objects.get
            )(expense_id=expense_id, trip=trip)
        except Expense.DoesNotExist:
            return {
                "success": False,
                "message": f"Expense {expense_id} not found in this trip.",
            }

        payer_id = await sync_to_async(lambda: expense.payer_id)()

        if caller_id not in (payer_id, participant_id):
            return {
                "success": False,
                "message": f"You can only settle costs you are involved in (expense {expense_id}).",
            }

        try:
            split = await sync_to_async(Split.objects.get)(
                expense_id=expense_id,
                participant_id=participant_id,
                expense__trip=trip,
            )
        except Split.DoesNotExist:
            return {
                "success": False,
                "message": f"Split not found for expense {expense_id}, participant {participant_id}.",
            }

        split.left_to_settlement_amount_in_cost_currency = ZERO
        split.left_to_settlement_amount_in_trip_currency = ZERO
        split.is_settlement = True
        await sync_to_async(split.save)()
        settled_count += 1

    await recalculate_settlements(trip)

    # Broadcast delta
    delta = await build_settlement_changed_delta(trip)
    await broadcast_delta(trip.trip_id, delta)

    return {
        "success": True,
        "message": f"Settled {settled_count} cost(s).",
    }