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
from TripApp.services.settlement_history import log_settlement
from TripApp.models import (
    Trip, Split, Expense, Participant, Prepayment, ParticipantRelation,
    SettlementHistory,
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

    pairs: set[tuple[int, int]] = set()

    left_trip: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    left_other: dict[tuple[int, int, str], Decimal] = defaultdict(lambda: ZERO)
    all_trip: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    all_other: dict[tuple[int, int, str], Decimal] = defaultdict(lambda: ZERO)
    prep_amount_left: dict[tuple[int, int, str], Decimal] = defaultdict(lambda: ZERO)
    prep_history: dict[tuple[int, int], list] = defaultdict(list)

    # Process splits
    for split in splits:
        from_id = split.participant_id
        to_id = split.expense.payer_id

        if from_id == to_id:
            continue

        pair = _ordered_pair(from_id, to_id)
        pairs.add(pair)

        sign = Decimal("1") if from_id == pair[1] else Decimal("-1")
        expense_currency = split.expense.expense_currency.upper()

        all_trip[pair] += sign * split.amount_in_trip_currency
        if expense_currency == trip_currency:
            all_other[(pair[0], pair[1], trip_currency)] += sign * split.amount_in_trip_currency
        else:
            all_other[(pair[0], pair[1], expense_currency)] += sign * split.amount_in_cost_currency

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

    # Process prepayments
    for prep in prepayments:
        from_id = prep.from_participant_id
        to_id = prep.to_participant_id

        if from_id == to_id:
            continue

        pair = _ordered_pair(from_id, to_id)
        pairs.add(pair)

        prep_currency = prep.currency.upper()
        sign_all = Decimal("-1") if from_id == pair[1] else Decimal("1")

        prep_amount_in_trip = (prep.amount * prep.rate).quantize(Decimal("0.01"))

        all_trip[pair] += sign_all * prep_amount_in_trip
        if prep_currency == trip_currency:
            all_other[(pair[0], pair[1], trip_currency)] += sign_all * prep.amount
        else:
            all_other[(pair[0], pair[1], prep_currency)] += sign_all * prep.amount

        if prep.amount_left > ZERO:
            left_in_trip = (prep.amount_left * prep.rate).quantize(Decimal("0.01"))
            left_trip[pair] += sign_all * left_in_trip
            if prep_currency == trip_currency:
                left_other[(pair[0], pair[1], trip_currency)] += sign_all * prep.amount_left
            else:
                left_other[(pair[0], pair[1], prep_currency)] += sign_all * prep.amount_left

        if prep.amount_left > ZERO:
            sign_prep = Decimal("1") if from_id == pair[0] else Decimal("-1")
            prep_amount_left[(pair[0], pair[1], prep_currency)] += sign_prep * prep.amount_left

        sign_hist = 1.0 if from_id == pair[0] else -1.0
        prep_history[pair].append({
            "date": prep.created_date.timestamp() * 1000,
            "values": {
                "is_main_currency": prep_currency == trip_currency,
                "currency": prep_currency,
                "amount": float(prep.amount) * sign_hist,
            },
        })

    await sync_to_async(ParticipantRelation.objects.filter(trip=trip).delete)()

    relations_to_create = []
    for pair in pairs:
        a_id, b_id = pair

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

        relations_to_create.append(ParticipantRelation(
            trip=trip,
            participant_a_id=a_id,
            participant_b_id=b_id,
            left_for_settled=left_for_settled_json,
            all_related_amount=all_related_json,
            prepayment_details=prepayment_details_json,
        ))

    if relations_to_create:
        await sync_to_async(
            lambda: ParticipantRelation.objects.bulk_create(relations_to_create)
        )()


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

    relevant_ids = {from_user_id, to_user_id}
    user = await sync_to_async(lambda: request.user)()

    all_participants = await sync_to_async(
        lambda: {
            p.participant_id: p
            for p in Participant.objects.filter(trip=trip, participant_id__in=relevant_ids)
        }
    )()

    from_participant = all_participants.get(from_user_id)
    if not from_participant:
        return {"success": False, "message": "From participant not found in this trip."}

    to_participant = all_participants.get(to_user_id)
    if not to_participant:
        return {"success": False, "message": "To participant not found in this trip."}

    if from_participant.participant_id == to_participant.participant_id:
        return {"success": False, "message": "Cannot settle with yourself."}

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

    # Phase 0: Validate max settleable from ParticipantRelation
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

    # Phase 1: Settle splits (FIFO by expense date)
    splits = await _load_settleable_splits(
        from_participant, to_participant, trip, currency, is_main_currency
    )

    remaining = amount_dec
    settled_expense_ids: list[int] = []
    settled_from_splits_settlement_curr = ZERO
    settled_from_splits_trip_curr = ZERO

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

            settled_from_splits_settlement_curr += settleable_trip
            settled_from_splits_trip_curr += settleable_trip
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

            settled_from_splits_settlement_curr += settleable_cost
            settled_from_splits_trip_curr += settleable_trip

        split.is_settlement = (
            split.left_to_settlement_amount_in_trip_currency <= ZERO
            and split.left_to_settlement_amount_in_cost_currency <= ZERO
        )
        await sync_to_async(split.save)()

        if expense.expense_id not in settled_expense_ids:
            settled_expense_ids.append(expense.expense_id)

    # Phase 2: Settle prepayments (FIFO by created_date)
    settled_from_prepayments_settlement_curr = ZERO
    settled_from_prepayments_trip_curr = ZERO

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

            settled_from_prepayments_settlement_curr += settleable
            prep_trip_amount = (settleable * prep.rate).quantize(Decimal("0.01"))
            settled_from_prepayments_trip_curr += prep_trip_amount

    # Phase 3: Log history, recalculate & broadcast
    actor_id = await get_actor_participant_id(request, trip)
    settle_currency = trip_currency if is_main_currency else currency

    if settled_from_splits_settlement_curr > ZERO:
        await log_settlement(
            trip=trip,
            from_participant_id=from_participant.participant_id,
            to_participant_id=to_participant.participant_id,
            settlement_type=SettlementHistory.SettlementType.MANUAL_BY_AMOUNT,
            amount_in_settlement_currency=settled_from_splits_settlement_curr,
            settlement_currency=settle_currency,
            amount_in_trip_currency=settled_from_splits_trip_curr,
            related_expense_ids=settled_expense_ids,
            actor_participant_id=actor_id,
        )

    if settled_from_prepayments_settlement_curr > ZERO:
        await log_settlement(
            trip=trip,
            from_participant_id=from_participant.participant_id,
            to_participant_id=to_participant.participant_id,
            settlement_type=SettlementHistory.SettlementType.MANUAL_BY_AMOUNT,
            amount_in_settlement_currency=settled_from_prepayments_settlement_curr,
            settlement_currency=settle_currency,
            amount_in_trip_currency=settled_from_prepayments_trip_curr,
            related_expense_ids=[],
            actor_participant_id=actor_id,
        )

    await recalculate_settlements(trip)

    settled_amount = amount_dec - remaining

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

    expense_ids = [item["expense_id"] for item in items]

    expenses_map = await sync_to_async(
        lambda: {
            e.expense_id: e
            for e in Expense.objects.filter(expense_id__in=expense_ids, trip=trip)
        }
    )()

    # Sprawdź czy wszystkie expenses istnieją
    for item in items:
        if item["expense_id"] not in expenses_map:
            return {
                "success": False,
                "message": f"Expense {item['expense_id']} not found in this trip.",
            }

    split_keys = [(item["expense_id"], item["participant_id"]) for item in items]
    all_splits = await sync_to_async(
        lambda: list(
            Split.objects.filter(
                expense_id__in=expense_ids,
                expense__trip=trip,
            )
        )
    )()
    splits_map = {(s.expense_id, s.participant_id): s for s in all_splits}

    settled_count = 0
    settlement_groups: dict[tuple[int, int], list[dict]] = defaultdict(list)

    for item in items:
        expense_id = item["expense_id"]
        participant_id = item["participant_id"]

        expense = expenses_map[expense_id]
        payer_id = expense.payer_id

        if caller_id not in (payer_id, participant_id):
            return {
                "success": False,
                "message": f"You can only settle costs you are involved in (expense {expense_id}).",
            }

        split = splits_map.get((expense_id, participant_id))
        if not split:
            return {
                "success": False,
                "message": f"Split not found for expense {expense_id}, participant {participant_id}.",
            }

        settled_cost = split.left_to_settlement_amount_in_cost_currency
        settled_trip = split.left_to_settlement_amount_in_trip_currency
        expense_currency = expense.expense_currency.upper()

        split.left_to_settlement_amount_in_cost_currency = ZERO
        split.left_to_settlement_amount_in_trip_currency = ZERO
        split.is_settlement = True
        await sync_to_async(split.save)()
        settled_count += 1

        pair_key = (participant_id, payer_id)
        settlement_groups[pair_key].append({
            "expense_id": expense_id,
            "settled_cost": settled_cost,
            "settled_trip": settled_trip,
            "expense_currency": expense_currency,
        })

    # Log history per pair
    actor_id = await get_actor_participant_id(request, trip)
    trip_currency = trip.default_currency.upper()

    for (from_id, to_id), group in settlement_groups.items():
        total_trip = sum(g["settled_trip"] for g in group)
        expense_ids_for_group = [g["expense_id"] for g in group]

        await log_settlement(
            trip=trip,
            from_participant_id=from_id,
            to_participant_id=to_id,
            settlement_type=SettlementHistory.SettlementType.MANUAL_BY_COSTS,
            amount_in_settlement_currency=total_trip,
            settlement_currency=trip_currency,
            amount_in_trip_currency=total_trip,
            related_expense_ids=expense_ids_for_group,
            actor_participant_id=actor_id,
        )

    await recalculate_settlements(trip)

    other_ids = set()
    for item in items:
        expense = expenses_map[item["expense_id"]]
        payer_id = expense.payer_id
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