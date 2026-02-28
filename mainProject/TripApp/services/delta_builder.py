"""
Delta builder — computes per-subscriber TripDelta after mutations.

Each build_*_delta function returns a dict that can be serialized and sent
through the channel layer. The subscription resolver then deserializes it
into TripDelta types with the subscriber's own settlement perspective.
"""

from collections import defaultdict
from decimal import Decimal
from asgiref.sync import sync_to_async
from TripApp.models import (
    Trip, Participant, Expense, Split, Prepayment,
    SettlementTripCurrency, SettlementOtherCurrency,
)

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Public API — called from services after mutations
# ---------------------------------------------------------------------------

async def build_expense_added_delta(trip: Trip, expense: Expense) -> dict:
    """Build delta payload after an expense is added."""
    return await _build_full_recalc_delta(
        trip,
        event_type="EXPENSE_ADDED",
        changed_expense_ids=[expense.expense_id],
    )


async def build_expense_updated_delta(trip: Trip, expense: Expense) -> dict:
    """Build delta payload after an expense is updated."""
    return await _build_full_recalc_delta(
        trip,
        event_type="EXPENSE_UPDATED",
        changed_expense_ids=[expense.expense_id],
    )


async def build_expense_deleted_delta(trip: Trip, expense_id: int) -> dict:
    """Build delta payload after an expense is deleted."""
    return await _build_full_recalc_delta(
        trip,
        event_type="EXPENSE_DELETED",
        removed_expense_ids=[expense_id],
    )


async def build_prepayment_delta(trip: Trip) -> dict:
    """Build delta payload after a prepayment is added."""
    return await _build_full_recalc_delta(
        trip,
        event_type="PREPAYMENT_ADDED",
    )


async def build_settlement_changed_delta(trip: Trip) -> dict:
    """Build delta payload after settle_by_amount or settle_by_costs."""
    return await _build_full_recalc_delta(
        trip,
        event_type="SETTLEMENT_CHANGED",
    )


async def build_participant_added_delta(trip: Trip, participant: Participant) -> dict:
    """Build delta after a placeholder is added."""
    return await _build_full_recalc_delta(
        trip,
        event_type="PARTICIPANT_ADDED",
        changed_participant_ids=[participant.participant_id],
    )


async def build_participant_updated_delta(trip: Trip, participant: Participant) -> dict:
    """Build delta after join_trip or detach_user."""
    return await _build_full_recalc_delta(
        trip,
        event_type="PARTICIPANT_UPDATED",
        changed_participant_ids=[participant.participant_id],
    )


async def build_participant_removed_delta(trip: Trip, participant_id: int) -> dict:
    """Build delta after a placeholder is removed."""
    return await _build_full_recalc_delta(
        trip,
        event_type="PARTICIPANT_REMOVED",
        removed_participant_ids=[participant_id],
    )


# ---------------------------------------------------------------------------
# Internal: build a "full recalc" delta
# ---------------------------------------------------------------------------

async def _build_full_recalc_delta(
    trip: Trip,
    event_type: str,
    changed_expense_ids: list[int] | None = None,
    removed_expense_ids: list[int] | None = None,
    changed_participant_ids: list[int] | None = None,
    removed_participant_ids: list[int] | None = None,
) -> dict:
    """
    Build a delta payload containing all the data needed for subscribers.

    This is a "shared" payload — it contains raw data that the subscription
    resolver will use to build per-user deltas (each user gets their own
    settlement perspective and my_cost).

    The payload is a plain dict so it can go through the channel layer.
    """
    trip_currency = trip.default_currency.upper()

    # Load all data
    all_participants = await sync_to_async(
        lambda: list(Participant.objects.filter(trip=trip).select_related("user"))
    )()

    all_expenses = await sync_to_async(
        lambda: list(
            Expense.objects.filter(trip=trip)
            .select_related("payer")
            .order_by("created_at")
        )
    )()

    all_splits = await sync_to_async(
        lambda: list(
            Split.objects.filter(expense__trip=trip)
            .select_related("expense", "participant")
        )
    )()

    all_prepayments = await sync_to_async(
        lambda: list(
            Prepayment.objects.filter(trip=trip)
            .select_related("from_participant", "to_participant")
            .order_by("created_date")
        )
    )()

    trip_settlements = await sync_to_async(
        lambda: list(
            SettlementTripCurrency.objects.filter(trip=trip)
            .select_related("from_participant", "to_participant")
        )
    )()

    other_settlements = await sync_to_async(
        lambda: list(
            SettlementOtherCurrency.objects.filter(trip=trip)
            .select_related("from_participant", "to_participant")
        )
    )()

    # Index
    splits_by_expense: dict[int, list] = defaultdict(list)
    for s in all_splits:
        splits_by_expense[s.expense_id].append(s)

    participant_map = {p.participant_id: p for p in all_participants}

    # Total expenses
    total_expenses = float(sum(e.amount_in_trip_currency for e in all_expenses) or 0)

    # Categories
    category_totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for e in all_expenses:
        category_totals[e.category] += e.amount_in_trip_currency

    categories = [
        {"category_id": cat_id, "total_amount": float(total)}
        for cat_id, total in category_totals.items()
    ]

    # Build changed expenses data
    changed_expenses_data = None
    if changed_expense_ids:
        changed_expenses_data = []
        for expense in all_expenses:
            if expense.expense_id in changed_expense_ids:
                changed_expenses_data.append(
                    _serialize_expense(expense, splits_by_expense, participant_map, trip_currency)
                )

    # Build participants data (always send all — totals change)
    participants_data = _serialize_participants(all_participants, all_splits, trip, trip_currency)

    # Pre-compute per-participant my_cost and settlement
    # (the subscription resolver picks the right one for each subscriber)
    per_participant = {}
    for p in all_participants:
        pid = p.participant_id
        my_cost = _compute_my_cost(all_splits, pid, trip_currency)
        settlement = _build_settlement(
            pid, trip_currency,
            trip_settlements, other_settlements,
            all_splits, all_prepayments, participant_map,
        )
        per_participant[pid] = {
            "my_cost": my_cost,
            "settlement": settlement,
        }

    return {
        "trip_id": trip.trip_id,
        "event_type": event_type,
        "expenses": changed_expenses_data,
        "removed_expense_ids": removed_expense_ids,
        "participants": participants_data,
        "removed_participant_ids": removed_participant_ids,
        "categories": categories,
        "total_expenses": total_expenses,
        "per_participant": per_participant,
    }


# ---------------------------------------------------------------------------
# Serializers (model → plain dict for channel layer)
# ---------------------------------------------------------------------------

def _serialize_expense(expense, splits_by_expense, participant_map, trip_currency) -> dict:
    splits = splits_by_expense.get(expense.expense_id, [])
    expense_currency = expense.expense_currency.upper()

    total_expense = [
        {"is_main_currency": True, "currency": trip_currency,
         "amount": float(expense.amount_in_trip_currency)}
    ]
    if expense_currency != trip_currency:
        total_expense.append(
            {"is_main_currency": False, "currency": expense_currency,
             "amount": float(expense.amount_in_expenses_currency)}
        )

    shared_with = []
    for split in splits:
        p = participant_map.get(split.participant_id)
        split_values = [
            {"is_main_currency": True, "currency": trip_currency,
             "amount": float(split.amount_in_trip_currency)}
        ]
        left_for_settlement = [
            {"is_main_currency": True, "currency": trip_currency,
             "amount": float(split.left_to_settlement_amount_in_trip_currency)}
        ]
        if expense_currency != trip_currency:
            split_values.append(
                {"is_main_currency": False, "currency": expense_currency,
                 "amount": float(split.amount_in_cost_currency)}
            )
            left_for_settlement.append(
                {"is_main_currency": False, "currency": expense_currency,
                 "amount": float(split.left_to_settlement_amount_in_cost_currency)}
            )
        shared_with.append({
            "participant_id": split.participant_id,
            "participant_nickname": p.nickname if p else "Unknown",
            "split_value": split_values,
            "is_settlement": split.is_settlement,
            "left_for_settlement": left_for_settlement,
        })

    payer = participant_map.get(expense.payer_id)

    return {
        "id": expense.expense_id,
        "name": expense.title,
        "description": expense.description,
        "total_expense": total_expense,
        "amount": float(expense.amount_in_expenses_currency),
        "currency": expense_currency,
        "date": expense.created_at.timestamp() * 1000,
        "category_id": expense.category,
        "payer_id": expense.payer_id,
        "payer_nickname": payer.nickname if payer else "Unknown",
        "shared_with": shared_with,
    }


def _serialize_participants(all_participants, all_splits, trip, trip_currency) -> list[dict]:
    splits_per_participant: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    trip_total_per_participant: dict[int, Decimal] = defaultdict(lambda: ZERO)

    for split in all_splits:
        pid = split.participant_id
        expense_currency = split.expense.expense_currency.upper()
        splits_per_participant[pid][expense_currency] += split.amount_in_cost_currency
        trip_total_per_participant[pid] += split.amount_in_trip_currency

    participants = []
    for p in all_participants:
        pid = p.participant_id
        currency_amounts = splits_per_participant.get(pid, {})
        trip_total = trip_total_per_participant.get(pid, ZERO)

        total_expenses = [
            {"is_main_currency": True, "currency": trip_currency, "amount": float(trip_total)}
        ]
        for curr, amount in currency_amounts.items():
            if curr != trip_currency:
                total_expenses.append(
                    {"is_main_currency": False, "currency": curr, "amount": float(amount)}
                )

        participants.append({
            "id": pid,
            "nickname": p.nickname,
            "total_expenses": total_expenses,
            "is_owner": p.user_id == trip.trip_owner_id,
            "is_placeholder": p.is_placeholder,
            "access_code": p.access_code,
            "is_active": not p.is_placeholder,
        })

    return participants


# ---------------------------------------------------------------------------
# Settlement & my_cost (reused from trip/service.py logic, serialized to dicts)
# ---------------------------------------------------------------------------

def _compute_my_cost(all_splits, my_id, trip_currency) -> list[dict]:
    cost_by_currency: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total_in_trip_currency = ZERO

    for split in all_splits:
        if split.participant_id != my_id:
            continue
        expense_currency = split.expense.expense_currency.upper()
        cost_by_currency[expense_currency] += split.amount_in_cost_currency
        total_in_trip_currency += split.amount_in_trip_currency

    result = [{"is_main_currency": True, "currency": trip_currency, "amount": float(total_in_trip_currency)}]
    for curr, amount in cost_by_currency.items():
        if curr != trip_currency:
            result.append({"is_main_currency": False, "currency": curr, "amount": float(amount)})

    return result


def _build_settlement(my_id, trip_currency, trip_settlements, other_settlements,
                      all_splits, all_prepayments, participant_map) -> dict | None:
    related_ids = set()

    for s in trip_settlements:
        if s.from_participant_id == my_id:
            related_ids.add(s.to_participant_id)
        elif s.to_participant_id == my_id:
            related_ids.add(s.from_participant_id)

    for s in other_settlements:
        if s.from_participant_id == my_id:
            related_ids.add(s.to_participant_id)
        elif s.to_participant_id == my_id:
            related_ids.add(s.from_participant_id)

    for split in all_splits:
        if split.is_settlement:
            continue
        payer_id = split.expense.payer_id
        participant_id = split.participant_id
        if payer_id == my_id and participant_id != my_id:
            related_ids.add(participant_id)
        elif participant_id == my_id and payer_id != my_id:
            related_ids.add(payer_id)

    for prep in all_prepayments:
        if prep.from_participant_id == my_id:
            related_ids.add(prep.to_participant_id)
        elif prep.to_participant_id == my_id:
            related_ids.add(prep.from_participant_id)

    if not related_ids:
        return None

    relations = []
    for other_id in related_ids:
        relations.append(_build_single_relation(
            my_id, other_id, trip_currency,
            trip_settlements, other_settlements,
            all_splits, all_prepayments, participant_map,
        ))

    return {"relations": relations}


def _build_single_relation(
    my_id: int,
    other_id: int,
    trip_currency: str,
    trip_settlements: list,
    other_settlements: list,
    all_splits: list,
    all_prepayments: list,
    participant_map: dict,
) -> dict:
    other_p = participant_map.get(other_id)

    # --- left_for_settled ---
    left_for_settled = []

    # From SettlementTripCurrency → is_main_currency: true
    left_trip = ZERO
    for s in trip_settlements:
        if s.from_participant_id == other_id and s.to_participant_id == my_id:
            left_trip += s.amount
        elif s.from_participant_id == my_id and s.to_participant_id == other_id:
            left_trip -= s.amount

    left_for_settled.append({
        "is_main_currency": True,
        "currency": trip_currency,
        "amount": float(left_trip),
    })

    # From SettlementOtherCurrency → is_main_currency: false
    left_other: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for s in other_settlements:
        if s.from_participant_id == other_id and s.to_participant_id == my_id:
            left_other[s.currency.upper()] += s.amount
        elif s.from_participant_id == my_id and s.to_participant_id == other_id:
            left_other[s.currency.upper()] -= s.amount

    for curr, amt in left_other.items():
        left_for_settled.append({
            "is_main_currency": False,
            "currency": curr,
            "amount": float(amt),
        })

    # --- all_related_amount ---
    all_related = []

    # Trip currency total (all splits converted) → is_main_currency: true
    all_related_trip = ZERO
    # Per original currency → is_main_currency: false
    all_related_other: dict[str, Decimal] = defaultdict(lambda: ZERO)

    for split in all_splits:
        if split.is_settlement:
            continue
        payer_id = split.expense.payer_id
        participant_id = split.participant_id
        expense_currency = split.expense.expense_currency.upper()

        if payer_id == my_id and participant_id == other_id:
            all_related_trip += split.amount_in_trip_currency
            if expense_currency == trip_currency:
                all_related_other[trip_currency] += split.amount_in_trip_currency
            else:
                all_related_other[expense_currency] += split.amount_in_cost_currency
        elif payer_id == other_id and participant_id == my_id:
            all_related_trip -= split.amount_in_trip_currency
            if expense_currency == trip_currency:
                all_related_other[trip_currency] -= split.amount_in_trip_currency
            else:
                all_related_other[expense_currency] -= split.amount_in_cost_currency

    all_related.append({
        "is_main_currency": True,
        "currency": trip_currency,
        "amount": float(all_related_trip),
    })
    for curr, amt in all_related_other.items():
        all_related.append({
            "is_main_currency": False,
            "currency": curr,
            "amount": float(amt),
        })

    # --- Prepayment details ---
    prepayment = _build_prepayment_details(
        my_id, other_id, trip_currency, all_prepayments
    )

    return {
        "related_id": other_id,
        "related_name": other_p.nickname if other_p else "Unknown",
        "left_for_settled": left_for_settled,
        "all_related_amount": all_related,
        "prepayment": prepayment,
    }

def _build_prepayment_details(my_id, other_id, trip_currency, all_prepayments) -> dict:
    amount_left_by_currency: dict[str, Decimal] = defaultdict(lambda: ZERO)
    history = []

    for prep in all_prepayments:
        is_from_me = (prep.from_participant_id == my_id and prep.to_participant_id == other_id)
        is_to_me = (prep.from_participant_id == other_id and prep.to_participant_id == my_id)

        if not is_from_me and not is_to_me:
            continue

        curr = prep.currency.upper()

        if prep.amount_left > ZERO:
            if is_from_me:
                amount_left_by_currency[curr] += prep.amount_left
            else:
                amount_left_by_currency[curr] -= prep.amount_left

        sign = Decimal("1") if is_from_me else Decimal("-1")
        history.append({
            "date": prep.created_date.timestamp() * 1000,
            "values": {
                "is_main_currency": curr == trip_currency,
                "currency": curr,
                "amount": float(sign * prep.amount),
            },
        })

    amount_left = []
    for curr, amt in amount_left_by_currency.items():
        amount_left.append({
            "is_main_currency": curr == trip_currency,
            "currency": curr,
            "amount": float(amt),
        })

    return {"amount_left": amount_left, "history": history}