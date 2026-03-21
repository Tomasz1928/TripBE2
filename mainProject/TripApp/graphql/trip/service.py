"""
Trip query service — builds TripListDto and TripDetailDto for the frontend.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from django.db.models import Sum, Q
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import (
    Trip, Participant, Expense, Split, Prepayment, ParticipantRelation,
    SettlementHistory,
)
from TripApp.services.breakdown import get_full_breakdown

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Trip List (lightweight)
# ---------------------------------------------------------------------------

async def get_trip_list(request: HttpRequest) -> list[dict]:
    """Return lightweight list of trips the user participates in."""
    user = await sync_to_async(lambda: request.user)()

    participants = await sync_to_async(
        lambda: list(
            Participant.objects.filter(user=user)
            .select_related("trip", "trip__trip_owner")
        )
    )()

    if not participants:
        return []

    trip_ids = [p.trip.trip_id for p in participants]
    expense_totals = await sync_to_async(
        lambda: dict(
            Expense.objects.filter(trip_id__in=trip_ids)
            .values_list("trip_id")
            .annotate(total=Sum("amount_in_trip_currency"))
            .values_list("trip_id", "total")
        )
    )()
    owner_participants = await sync_to_async(
        lambda: {
            p.trip_id: p
            for p in Participant.objects.filter(
                trip_id__in=trip_ids,
                user_id__in=[p.trip.trip_owner_id for p in participants]
            ).filter()
        }
    )()

    trip_owner_map = {p.trip.trip_id: p.trip.trip_owner_id for p in participants}
    owner_participants_list = await sync_to_async(
        lambda: list(
            Participant.objects.filter(trip_id__in=trip_ids, is_placeholder=False)
            .only("participant_id", "trip_id", "user_id")
        )
    )()
    owner_participant_map = {}
    for op in owner_participants_list:
        if op.user_id == trip_owner_map.get(op.trip_id):
            owner_participant_map[op.trip_id] = op.participant_id

    trips = []
    for p in participants:
        trip = p.trip
        total = expense_totals.get(trip.trip_id, Decimal("0"))

        trips.append({
            "id": trip.trip_id,
            "title": trip.title,
            "date_start": trip.start_date.timestamp() * 1000,
            "date_end": trip.end_date.timestamp() * 1000,
            "currency": trip.default_currency,
            "description": trip.description,
            "total_expenses": float(total or 0),
            "owner_id": owner_participant_map.get(trip.trip_id),
            "im_owner": p.user_id == trip.trip_owner_id,
        })

    return trips


# ---------------------------------------------------------------------------
# Trip Details (full)
# ---------------------------------------------------------------------------

async def get_trip_details(request: HttpRequest, trip_id: int) -> dict:
    """Return full trip data matching TripDto on FE."""
    user = await sync_to_async(lambda: request.user)()
    trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)
    trip_currency = trip.default_currency.upper()

    my_participant = await sync_to_async(
        lambda: Participant.objects.filter(trip=trip, user=user).first()
    )()
    if not my_participant:
        return None

    my_id = my_participant.participant_id

    # --- Load all data upfront ---
    all_participants = await sync_to_async(
        lambda: list(Participant.objects.filter(trip=trip).select_related("user"))
    )()

    owner_participant = next(
        (p for p in all_participants if p.user_id == trip.trip_owner_id), None
    )
    owner_participant_id = owner_participant.participant_id if owner_participant else None

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

    # Load ParticipantRelation records for my relations
    my_relations = await sync_to_async(
        lambda: list(
            ParticipantRelation.objects.filter(trip=trip).filter(
                models_q_participant_a_or_b(my_id)
            )
        )
    )()

    # Load settlement history only for my relations (single query)
    my_history = await sync_to_async(
        lambda: list(
            SettlementHistory.objects.filter(trip=trip)
            .filter(models_q_participant_a_or_b(my_id))
            .select_related("actor_participant")
            .order_by("-created_at")
        )
    )()

    # Group history by ordered pair (a_id, b_id) for efficient lookup
    history_by_pair: dict[tuple[int, int], list] = defaultdict(list)
    for record in my_history:
        pair = (record.participant_a_id, record.participant_b_id)
        history_by_pair[pair].append(record)

    splits_by_expense: dict[int, list] = defaultdict(list)
    for s in all_splits:
        splits_by_expense[s.expense_id].append(s)

    participant_map = {p.participant_id: p for p in all_participants}
    expense_map = {e.expense_id: e.title for e in all_expenses}

    total_expenses = float(sum(e.amount_in_trip_currency for e in all_expenses) or 0)

    category_totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for e in all_expenses:
        category_totals[e.category] += e.amount_in_trip_currency

    categories = [
        {"category_id": cat_id, "total_amount": float(total)}
        for cat_id, total in category_totals.items()
    ]

    my_cost = _compute_my_cost(all_splits, my_id, trip_currency)
    expenses = _build_expenses(all_expenses, splits_by_expense, participant_map, trip_currency)
    participants = _build_participants(all_participants, all_splits, trip, trip_currency)

    settlement = _build_settlement_from_relations(
        my_id, my_relations, participant_map, history_by_pair, expense_map
    )

    return {
        "id": trip.trip_id,
        "title": trip.title,
        "date_start": trip.start_date.timestamp() * 1000,
        "date_end": trip.end_date.timestamp() * 1000,
        "currency": trip.default_currency,
        "description": trip.description,
        "total_expenses": total_expenses,
        "categories": categories,
        "owner_id": owner_participant_id,
        "im_owner": owner_participant_id == my_id,
        "my_participant_id": my_id,
        "my_cost": my_cost,
        "expenses": expenses,
        "participants": participants,
        "settlement": settlement,
    }


def models_q_participant_a_or_b(participant_id: int):
    """Build Q filter for ParticipantRelation where participant is A or B."""
    return Q(participant_a_id=participant_id) | Q(participant_b_id=participant_id)


# ---------------------------------------------------------------------------
# Helper: my cost
# ---------------------------------------------------------------------------

def _compute_my_cost(
    all_splits: list, my_id: int, trip_currency: str
) -> list[dict]:
    cost_by_currency: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total_in_trip_currency = ZERO

    for split in all_splits:
        if split.participant_id != my_id:
            continue
        expense_currency = split.expense.expense_currency.upper()
        cost_by_currency[expense_currency] += split.amount_in_cost_currency
        total_in_trip_currency += split.amount_in_trip_currency

    result = [
        {
            "is_main_currency": True,
            "currency": trip_currency,
            "amount": float(total_in_trip_currency),
        }
    ]

    for curr, amount in cost_by_currency.items():
        if curr != trip_currency:
            result.append({
                "is_main_currency": False,
                "currency": curr,
                "amount": float(amount),
            })

    return result


# ---------------------------------------------------------------------------
# Helper: build expenses
# ---------------------------------------------------------------------------

def _build_expenses(
    all_expenses: list,
    splits_by_expense: dict,
    participant_map: dict,
    trip_currency: str,
) -> list[dict]:
    expenses = []

    for expense in all_expenses:
        splits = splits_by_expense.get(expense.expense_id, [])
        expense_currency = expense.expense_currency.upper()

        total_expense = [
            {
                "is_main_currency": True,
                "currency": trip_currency,
                "amount": float(expense.amount_in_trip_currency),
            }
        ]
        if expense_currency != trip_currency:
            total_expense.append({
                "is_main_currency": False,
                "currency": expense_currency,
                "amount": float(expense.amount_in_expenses_currency),
            })

        shared_with = []
        for split in splits:
            p = participant_map.get(split.participant_id)
            split_values = [
                {
                    "is_main_currency": True,
                    "currency": trip_currency,
                    "amount": float(split.amount_in_trip_currency),
                }
            ]
            left_for_settlement = [
                {
                    "is_main_currency": True,
                    "currency": trip_currency,
                    "amount": float(split.left_to_settlement_amount_in_trip_currency),
                }
            ]
            if expense_currency != trip_currency:
                split_values.append({
                    "is_main_currency": False,
                    "currency": expense_currency,
                    "amount": float(split.amount_in_cost_currency),
                })
                left_for_settlement.append({
                    "is_main_currency": False,
                    "currency": expense_currency,
                    "amount": float(split.left_to_settlement_amount_in_cost_currency),
                })

            # Settlement breakdown — read from JSON field, compute UNSETTLED
            breakdown = get_full_breakdown(split)

            shared_with.append({
                "participant_id": split.participant_id,
                "participant_nickname": p.nickname if p else "Unknown",
                "split_value": split_values,
                "is_settlement": split.is_settlement,
                "left_for_settlement": left_for_settlement,
                "settlement_breakdown": breakdown,
            })

        payer = participant_map.get(expense.payer_id)

        expenses.append({
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
        })

    return expenses


# ---------------------------------------------------------------------------
# Helper: build participants
# ---------------------------------------------------------------------------

def _build_participants(
    all_participants: list,
    all_splits: list,
    trip: object,
    trip_currency: str,
) -> list[dict]:
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
            {
                "is_main_currency": True,
                "currency": trip_currency,
                "amount": float(trip_total),
            }
        ]
        for curr, amount in currency_amounts.items():
            if curr != trip_currency:
                total_expenses.append({
                    "is_main_currency": False,
                    "currency": curr,
                    "amount": float(amount),
                })

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
# Helper: build settlement from ParticipantRelation (read from DB)
# ---------------------------------------------------------------------------

def _build_settlement_from_relations(
    my_id: int,
    my_relations: list,
    participant_map: dict,
    history_by_pair: dict[tuple[int, int], list],
    expense_map: dict[int, str],
) -> dict:
    relations = []

    for rel in my_relations:
        if rel.participant_a_id == my_id:
            other_id = rel.participant_b_id
            sign = 1.0
        else:
            other_id = rel.participant_a_id
            sign = -1.0

        other_p = participant_map.get(other_id)

        left_for_settled = [
            {
                "is_main_currency": entry["is_main_currency"],
                "currency": entry["currency"],
                "amount": entry["amount"] * sign,
            }
            for entry in rel.left_for_settled
        ]

        all_related_amount = [
            {
                "is_main_currency": entry["is_main_currency"],
                "currency": entry["currency"],
                "amount": entry["amount"] * sign,
            }
            for entry in rel.all_related_amount
        ]

        prepayment_details = rel.prepayment_details or {"amount_left": [], "history": []}

        amount_left = [
            {
                "is_main_currency": entry["is_main_currency"],
                "currency": entry["currency"],
                "amount": entry["amount"] * sign,
            }
            for entry in prepayment_details.get("amount_left", [])
        ]

        history = [
            {
                "date": h["date"],
                "values": {
                    "is_main_currency": h["values"]["is_main_currency"],
                    "currency": h["values"]["currency"],
                    "amount": h["values"]["amount"] * sign,
                },
            }
            for h in prepayment_details.get("history", [])
        ]

        # Settlement history for this specific relation
        pair = (
            min(my_id, other_id),
            max(my_id, other_id),
        )
        pair_history = history_by_pair.get(pair, [])
        settlement_history = _build_relation_settlement_history(
            my_id, pair_history, participant_map, expense_map
        )

        relations.append({
            "related_id": other_id,
            "related_name": other_p.nickname if other_p else "Unknown",
            "left_for_settled": left_for_settled,
            "all_related_amount": all_related_amount,
            "prepayment": {
                "amount_left": amount_left,
                "history": history,
            },
            "settlement_history": settlement_history,
        })

    return {"relations": relations}


# ---------------------------------------------------------------------------
# Helper: build settlement history for a single relation (from my perspective)
# ---------------------------------------------------------------------------

def _build_relation_settlement_history(
    my_id: int,
    history_records: list,
    participant_map: dict,
    expense_map: dict[int, str],
) -> list[dict]:
    """
    Build settlement history entries for a single relation.

    Sign convention: positive = I paid/settled towards the other person,
    negative = the other person paid/settled towards me.
    """
    result = []

    for record in history_records:
        # Determine sign: if I am participant_a, use raw values;
        # if I am participant_b, flip sign.
        if record.participant_a_id == my_id:
            sign = 1.0
        else:
            sign = -1.0

        actor_nickname = None
        if record.actor_participant_id is not None:
            actor_p = participant_map.get(record.actor_participant_id)
            actor_nickname = actor_p.nickname if actor_p else "Unknown"

        related_names = [
            expense_map.get(eid, "Unknown")
            for eid in (record.related_expenses or [])
        ]

        result.append({
            "id": record.id,
            "settlement_type": record.settlement_type,
            "actor_nickname": actor_nickname,
            "amount_in_settlement_currency": float(record.amount_in_settlement_currency) * sign,
            "settlement_currency": record.settlement_currency,
            "amount_in_trip_currency": float(record.amount_in_trip_currency) * sign,
            "related_expense_names": related_names,
            "created_at": record.created_at.timestamp() * 1000,
        })

    return result


# ---------------------------------------------------------------------------
# Create trip
# ---------------------------------------------------------------------------

async def create_trip(
    request: HttpRequest, title: str, date_start: int, date_end: int,
    description: str, currency: str,
) -> dict:
    title = title.strip()
    currency = currency.strip().upper()
    description = description.strip()

    if not title:
        return {"success": False, "message": "Title is required."}
    if len(title) > 40:
        return {"success": False, "message": "Title must be at most 40 characters."}
    if not currency:
        return {"success": False, "message": "Currency is required."}
    if date_end <= date_start:
        return {"success": False, "message": "End date must be after start date."}

    start_date = datetime.fromtimestamp(date_start / 1000, tz=timezone.utc)
    end_date = datetime.fromtimestamp(date_end / 1000, tz=timezone.utc)

    user = await sync_to_async(lambda: request.user)()

    trip = await sync_to_async(Trip.objects.create)(
        trip_owner=user,
        title=title,
        description=description,
        start_date=start_date,
        end_date=end_date,
        default_currency=currency,
    )

    await sync_to_async(Participant.objects.create)(
        trip=trip,
        user=user,
        nickname=user.username,
        is_placeholder=False,
        access_code=None,
    )

    return {"success": True, "message": "Trip created successfully.", "trip": trip}