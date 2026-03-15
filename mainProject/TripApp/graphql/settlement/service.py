"""
Settlement service:
  - recalculate_settlements: rebuild ParticipantRelation records for a trip
  - settle_by_amount: FIFO settlement (splits first, then prepayments), reads limits from ParticipantRelation
  - settle_by_costs: mark specific splits as fully settled
"""

from collections import defaultdict
from decimal import Decimal
from django.http import HttpRequest
from asgiref.sync import sync_to_async

from TripApp.services.actor_resolver import get_actor_participant_id
from TripApp.services.broadcast import broadcast_delta
from TripApp.services.delta_builder import build_settlement_changed_notification
from TripApp.services.exchange import get_exchange_rate
from TripApp.models import (
    Trip, Split, Expense, Participant, Prepayment, ParticipantRelation,
)

ZERO = Decimal("0.00")


def _ordered_pair(id_a: int, id_b: int) -> tuple[int, int]:
    """Ensure participant_a.id < participant_b.id convention."""
    return (min(id_a, id_b), max(id_a, id_b))


# ---------------------------------------------------------------------------
# Recalculate settlements → rebuild ParticipantRelation
# ---------------------------------------------------------------------------

async def recalculate_settlements(trip: Trip) -> None:
    """
    Rebuild all ParticipantRelation records for a trip from scratch.

    Each relation stores:
      - left_for_settled: net unsettled debt (splits + unused prepayments)
      - all_related_amount: net total of ALL splits + ALL prepayments (full amounts)
      - prepayment_details: amount_left + history

    Sign convention (ordered pair where A.id < B.id):
      positive = B owes A, negative = A owes B
    """
    trip_currency = trip.default_currency.upper()

    splits = await sync_to_async(
        lambda: list(
            Split.objects.filter(expense__trip=trip)
            .select_related("expense", "participant")
        )
    )()

    prepayments = await sync_to_async(
        lambda: list(
            Prepayment.objects.filter(trip=trip)
            .select_related("from_participant", "to_participant")
            .order_by("created_date")
        )
    )()

    # Collect all pairs that have any relation
    pairs: set[tuple[int, int]] = set()

    # ------------------------------------------------------------------
    # Accumulators keyed by ordered pair (a_id, b_id)
    # ------------------------------------------------------------------

    # left_for_settled: unsettled debts
    left_trip: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    left_other: dict[tuple[int, int, str], Decimal] = defaultdict(lambda: ZERO)

    # all_related_amount: full amounts (splits + prepayments)
    all_trip: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    all_other: dict[tuple[int, int, str], Decimal] = defaultdict(lambda: ZERO)

    # prepayment accumulators
    prep_amount_left: dict[tuple[int, int, str], Decimal] = defaultdict(lambda: ZERO)
    prep_history: dict[tuple[int, int], list] = defaultdict(list)

    # ------------------------------------------------------------------
    # Process splits
    # ------------------------------------------------------------------
    for split in splits:
        from_id = split.participant_id  # owes
        to_id = split.expense.payer_id  # is owed

        if from_id == to_id:
            continue

        pair = _ordered_pair(from_id, to_id)
        pairs.add(pair)

        # Sign: from_id owes to_id.
        # If from_id is B (larger) → positive (B owes A) ✓
        # If from_id is A (smaller) → negative (A owes B) ✓
        sign = Decimal("1") if from_id == pair[1] else Decimal("-1")

        expense_currency = split.expense.expense_currency.upper()

        # --- all_related_amount (full amounts, ALL splits) ---
        all_trip[pair] += sign * split.amount_in_trip_currency
        if expense_currency == trip_currency:
            all_other[(pair[0], pair[1], trip_currency)] += sign * split.amount_in_trip_currency
        else:
            all_other[(pair[0], pair[1], expense_currency)] += sign * split.amount_in_cost_currency

        # --- left_for_settled (only unsettled) ---
        left_trip_amt = split.left_to_settlement_amount_in_trip_currency
        left_cost_amt = split.left_to_settlement_amount_in_cost_currency

        if left_trip_amt <= ZERO and left_cost_amt <= ZERO:
            continue

        if left_trip_amt > ZERO:
            left_trip[pair] += sign * left_trip_amt

        if expense_currency == trip_currency:
            if left_trip_amt > ZERO:
                left_other[(pair[0], pair[1], trip_currency)] += sign * left_trip_amt
        else:
            if left_cost_amt > ZERO:
                left_other[(pair[0], pair[1], expense_currency)] += sign * left_cost_amt

    # ------------------------------------------------------------------
    # Process prepayments
    # ------------------------------------------------------------------
    for prep in prepayments:
        from_id = prep.from_participant_id  # gave money
        to_id = prep.to_participant_id      # received money

        if from_id == to_id:
            continue

        pair = _ordered_pair(from_id, to_id)
        pairs.add(pair)

        prep_currency = prep.currency.upper()

        # from_id gave money to to_id → from_id's debt to to_id decreases.
        # Opposite sign to splits: if from_id is B → negative, if from_id is A → positive
        sign_all = Decimal("-1") if from_id == pair[1] else Decimal("1")

        prep_amount_in_trip = (prep.amount * prep.rate).quantize(Decimal("0.01"))

        # all_related_amount (full amount)
        all_trip[pair] += sign_all * prep_amount_in_trip
        if prep_currency == trip_currency:
            all_other[(pair[0], pair[1], trip_currency)] += sign_all * prep.amount
        else:
            all_other[(pair[0], pair[1], prep_currency)] += sign_all * prep.amount

        # left_for_settled (only unused prepayment balance → reverse debt)
        if prep.amount_left > ZERO:
            left_in_trip = (prep.amount_left * prep.rate).quantize(Decimal("0.01"))
            left_trip[pair] += sign_all * left_in_trip
            if prep_currency == trip_currency:
                left_other[(pair[0], pair[1], trip_currency)] += sign_all * prep.amount_left
            else:
                left_other[(pair[0], pair[1], prep_currency)] += sign_all * prep.amount_left

        # Prepayment details: amount_left
        if prep.amount_left > ZERO:
            # from A's perspective: A prepaid → positive, B prepaid → negative
            sign_prep = Decimal("1") if from_id == pair[0] else Decimal("-1")
            prep_amount_left[(pair[0], pair[1], prep_currency)] += sign_prep * prep.amount_left

        # Prepayment details: history (always full amount)
        sign_hist = 1.0 if from_id == pair[0] else -1.0
        prep_history[pair].append({
            "date": prep.created_date.timestamp() * 1000,
            "values": {
                "is_main_currency": prep_currency == trip_currency,
                "currency": prep_currency,
                "amount": float(prep.amount) * sign_hist,
            },
        })

    # ------------------------------------------------------------------
    # Build and persist ParticipantRelation records
    # ------------------------------------------------------------------
    await sync_to_async(ParticipantRelation.objects.filter(trip=trip).delete)()

    for pair in pairs:
        a_id, b_id = pair

        # left_for_settled JSON
        left_for_settled_json = []
        lft = left_trip.get(pair, ZERO)
        left_for_settled_json.append({
            "is_main_currency": True,
            "currency": trip_currency,
            "amount": float(lft.quantize(Decimal("0.01"))),
        })
        for (pa, pb, curr), amt in left_other.items():
            if (pa, pb) == pair and curr != trip_currency:
                left_for_settled_json.append({
                    "is_main_currency": False,
                    "currency": curr,
                    "amount": float(amt.quantize(Decimal("0.01"))),
                })

        # all_related_amount JSON
        all_related_json = []
        art = all_trip.get(pair, ZERO)
        all_related_json.append({
            "is_main_currency": True,
            "currency": trip_currency,
            "amount": float(art.quantize(Decimal("0.01"))),
        })
        for (pa, pb, curr), amt in all_other.items():
            if (pa, pb) == pair and curr != trip_currency:
                all_related_json.append({
                    "is_main_currency": False,
                    "currency": curr,
                    "amount": float(amt.quantize(Decimal("0.01"))),
                })

        # prepayment_details JSON
        amount_left_json = []
        for (pa, pb, curr), amt in prep_amount_left.items():
            if (pa, pb) == pair:
                amount_left_json.append({
                    "is_main_currency": curr == trip_currency,
                    "currency": curr,
                    "amount": float(amt.quantize(Decimal("0.01"))),
                })

        history_json = prep_history.get(pair, [])

        prepayment_details_json = {
            "amount_left": amount_left_json,
            "history": history_json,
        }

        await sync_to_async(ParticipantRelation.objects.create)(
            trip=trip,
            participant_a_id=a_id,
            participant_b_id=b_id,
            left_for_settled=left_for_settled_json,
            all_related_amount=all_related_json,
            prepayment_details=prepayment_details_json,
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

    # -----------------------------------------------------------------------
    # Phase 0: Validate max settleable from ParticipantRelation
    # -----------------------------------------------------------------------
    a_id, b_id = _ordered_pair(from_participant.participant_id, to_participant.participant_id)

    relation = await sync_to_async(
        lambda: ParticipantRelation.objects.filter(
            trip=trip, participant_a_id=a_id, participant_b_id=b_id
        ).first()
    )()

    if not relation:
        return {"success": False, "message": "No debts found between these participants."}

    max_settleable = _extract_max_settleable(
        relation.left_for_settled,
        from_participant.participant_id,
        b_id,
        currency,
        is_main_currency,
    )

    if amount_dec > max_settleable:
        settle_currency = trip_currency if is_main_currency else currency
        return {
            "success": False,
            "message": f"Amount exceeds maximum settleable ({max_settleable} {settle_currency}).",
        }

    # -----------------------------------------------------------------------
    # Phase 1: Settle splits (FIFO by expense date)
    # -----------------------------------------------------------------------
    splits = await _load_settleable_splits(
        from_participant, to_participant, trip, currency, is_main_currency
    )

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

    # -----------------------------------------------------------------------
    # Phase 2: Settle prepayments (FIFO by created_date)
    # -----------------------------------------------------------------------
    if remaining > ZERO:
        prepayments = await _load_settleable_prepayments(
            from_participant, to_participant, trip, currency, is_main_currency, trip_currency
        )

        for prep in prepayments:
            if remaining <= ZERO:
                break

            settleable = min(remaining, prep.amount_left)
            prep.amount_left -= settleable
            remaining -= settleable
            await sync_to_async(prep.save)()

    # -----------------------------------------------------------------------
    # Phase 3: Recalculate & broadcast
    # -----------------------------------------------------------------------
    await recalculate_settlements(trip)

    settled_amount = amount_dec - remaining

    actor_id = await get_actor_participant_id(request, trip)
    if actor_id == from_participant.participant_id:
        target_id = to_participant.participant_id
    else:
        target_id = from_participant.participant_id

    notification = await build_settlement_changed_notification(trip, actor_id, target_id)
    await broadcast_delta(trip.trip_id, notification)

    return {
        "success": True,
        "message": f"Settled {settled_amount} {currency}.",
    }


# ---------------------------------------------------------------------------
# Settle by amount — helpers
# ---------------------------------------------------------------------------

def _extract_max_settleable(
    left_for_settled: list[dict],
    from_id: int,
    b_id: int,
    currency: str,
    is_main_currency: bool,
) -> Decimal:
    """
    Extract max settleable amount from left_for_settled JSON.
    Handles sign convention: positive = B owes A.
    from_id is the one who owes → if from_id == B, take positive values.
    """
    for entry in left_for_settled:
        if is_main_currency and entry.get("is_main_currency"):
            raw = Decimal(str(entry["amount"]))
            return max(ZERO, raw if from_id == b_id else -raw)
        elif not is_main_currency and not entry.get("is_main_currency") and entry.get("currency", "").upper() == currency:
            raw = Decimal(str(entry["amount"]))
            return max(ZERO, raw if from_id == b_id else -raw)
    return ZERO


async def _load_settleable_splits(
    from_participant: Participant,
    to_participant: Participant,
    trip: Trip,
    currency: str,
    is_main_currency: bool,
) -> list:
    """Load unsettled splits eligible for settlement, FIFO by expense date."""
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

    return await sync_to_async(lambda: list(base_qs))()


async def _load_settleable_prepayments(
    from_participant: Participant,
    to_participant: Participant,
    trip: Trip,
    currency: str,
    is_main_currency: bool,
    trip_currency: str,
) -> list:
    """
    Load prepayments eligible for settlement, FIFO by created_date.
    These are prepayments where to_participant gave money to from_participant.
    """
    prep_currency = trip_currency if is_main_currency else currency

    return await sync_to_async(
        lambda: list(
            Prepayment.objects.filter(
                trip=trip,
                from_participant_id=to_participant.participant_id,
                to_participant_id=from_participant.participant_id,
                amount_left__gt=ZERO,
                currency__iexact=prep_currency,
            ).order_by("created_date")
        )
    )()


# ---------------------------------------------------------------------------
# Settle by costs
# ---------------------------------------------------------------------------

async def settle_by_costs(
    request: HttpRequest,
    trip_id: int,
    items: list[dict],
) -> dict:

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

    actor_id = await get_actor_participant_id(request, trip)
    other_ids = set()
    for item in items:
        expense = await sync_to_async(Expense.objects.get)(expense_id=item["expense_id"], trip=trip)
        payer_id = await sync_to_async(lambda: expense.payer_id)()
        participant_id = item["participant_id"]
        if actor_id == payer_id:
            other_ids.add(participant_id)
        else:
            other_ids.add(payer_id)

    for target_id in other_ids:
        notification = await build_settlement_changed_notification(trip, actor_id, target_id)
        await broadcast_delta(trip.trip_id, notification)

    return {
        "success": True,
        "message": f"Settled {settled_count} cost(s).",
    }