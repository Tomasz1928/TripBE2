"""
Trip query service — builds TripListDto and TripDetailDto for the frontend.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import (
    Trip, Participant, Expense, Split, Prepayment, ParticipantRelation,
    SettlementHistory,
)

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

    trips = []
    for p in participants:
        trip = p.trip
        total = await sync_to_async(
            lambda t=trip: sum(
                e.amount_in_trip_currency
                for e in Expense.objects.filter(trip=t)
            ) or Decimal("0")
        )()

        owner_participant = await sync_to_async(
            lambda t=trip: Participant.objects.filter(trip=t, user=t.trip_owner).first()
        )()
        owner_participant_id = owner_participant.participant_id if owner_participant else None

        trips.append({
            "id": trip.trip_id,
            "title": trip.title,
            "date_start": trip.start_date.timestamp() * 1000,
            "date_end": trip.end_date.timestamp() * 1000,
            "currency": trip.default_currency,
            "description": trip.description,
            "total_expenses": float(total),
            "owner_id": owner_participant_id,
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

    splits_by_expense: dict[int, list] = defaultdict(list)
    for s in all_splits:
        splits_by_expense[s.expense_id].append(s)

    participant_map = {p.participant_id: p for p in all_participants}

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

    # --- Settlement (from ParticipantRelation) ---
    settlement = _build_settlement_from_relations(my_id, my_relations, participant_map)

    # --- Settlement History ---
    my_history = await sync_to_async(
        lambda: list(
            SettlementHistory.objects.filter(trip=trip).filter(
                models_q_participant_a_or_b(my_id)
            ).select_related("participant_a", "participant_b", "actor_participant")
            .order_by("-created_at")
        )
    )()
    settlement_history = _build_settlement_history(my_id, my_history, participant_map)

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
        "settlement_history": settlement_history,
    }


def models_q_participant_a_or_b(participant_id: int):
    """Build Q filter for ParticipantRelation where participant is A or B."""
    from django.db.models import Q
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

            shared_with.append({
                "participant_id": split.participant_id,
                "participant_nickname": p.nickname if p else "Unknown",
                "split_value": split_values,
                "is_settlement": split.is_settlement,
                "left_for_settlement": left_for_settlement,
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
) -> dict:
    """
    Build SettlementDto from precomputed ParticipantRelation records.

    ParticipantRelation sign convention: positive = B owes A (where A.id < B.id).
    We need to flip signs when presenting from my_id's perspective:
      - "positive = other owes me" in the API response.
    """
    relations = []

    for rel in my_relations:
        if rel.participant_a_id == my_id:
            other_id = rel.participant_b_id
            # I am A. Convention: positive = B owes A = other owes me. No flip needed.
            sign = 1.0
        else:
            other_id = rel.participant_a_id
            # I am B. Convention: positive = B owes A = I owe other. Flip sign.
            sign = -1.0

        other_p = participant_map.get(other_id)

        # Flip signs in left_for_settled
        left_for_settled = [
            {
                "is_main_currency": entry["is_main_currency"],
                "currency": entry["currency"],
                "amount": entry["amount"] * sign,
            }
            for entry in rel.left_for_settled
        ]

        # Flip signs in all_related_amount
        all_related_amount = [
            {
                "is_main_currency": entry["is_main_currency"],
                "currency": entry["currency"],
                "amount": entry["amount"] * sign,
            }
            for entry in rel.all_related_amount
        ]

        # Flip signs in prepayment_details
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

        relations.append({
            "related_id": other_id,
            "related_name": other_p.nickname if other_p else "Unknown",
            "left_for_settled": left_for_settled,
            "all_related_amount": all_related_amount,
            "prepayment": {
                "amount_left": amount_left,
                "history": history,
            },
        })

    return {"relations": relations}


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

    from datetime import datetime, timezone

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


# ---------------------------------------------------------------------------
# Helper: build settlement history (from my perspective)
# ---------------------------------------------------------------------------

def _build_settlement_history(
    my_id: int,
    history_records: list,
    participant_map: dict,
) -> list[dict]:
    """
    Build settlement history list from SettlementHistory records.

    For each record, determine which participant is "the other" relative to my_id,
    and present actor info.
    """
    result = []

    for record in history_records:
        # Determine other participant
        if record.participant_a_id == my_id:
            other_id = record.participant_b_id
        else:
            other_id = record.participant_a_id

        other_p = participant_map.get(other_id)

        # Actor info
        actor_id = None
        actor_nickname = None
        if record.actor_participant_id is not None:
            actor_id = record.actor_participant_id
            actor_p = participant_map.get(actor_id)
            actor_nickname = actor_p.nickname if actor_p else "Unknown"

        result.append({
            "id": record.id,
            "settlement_type": record.settlement_type,
            "actor_participant_id": actor_id,
            "actor_nickname": actor_nickname,
            "other_participant_id": other_id,
            "other_nickname": other_p.nickname if other_p else "Unknown",
            "amount_in_settlement_currency": float(record.amount_in_settlement_currency),
            "settlement_currency": record.settlement_currency,
            "amount_in_trip_currency": float(record.amount_in_trip_currency),
            "related_expense_ids": record.related_expenses or [],
            "created_at": record.created_at.timestamp() * 1000,
        })

    return result