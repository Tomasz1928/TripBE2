"""
Trip query service — builds TripListDto and TripDetailDto for the frontend.
"""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import (
    Trip, Participant, Expense, Split, Prepayment,
    SettlementTripCurrency, SettlementOtherCurrency,
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
        # Total expenses in trip currency
        total = await sync_to_async(
            lambda t=trip: sum(
                e.amount_in_trip_currency
                for e in Expense.objects.filter(trip=t)
            ) or Decimal("0")
        )()

        # Find owner's participant_id for this trip
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

    # Verify user is participant
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

    # Find owner's participant_id
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

    # Index splits by expense
    splits_by_expense: dict[int, list] = defaultdict(list)
    for s in all_splits:
        splits_by_expense[s.expense_id].append(s)

    # Participant map
    participant_map = {p.participant_id: p for p in all_participants}

    # --- Total expenses (trip currency) ---
    total_expenses = float(sum(e.amount_in_trip_currency for e in all_expenses) or 0)

    # --- Categories ---
    category_totals: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for e in all_expenses:
        category_totals[e.category] += e.amount_in_trip_currency

    categories = [
        {"category_id": cat_id, "total_amount": float(total)}
        for cat_id, total in category_totals.items()
    ]

    # --- My cost ---
    my_cost = _compute_my_cost(all_splits, my_id, trip_currency)

    # --- Expenses ---
    expenses = _build_expenses(all_expenses, splits_by_expense, participant_map, trip_currency)

    # --- Participants ---
    participants = _build_participants(
        all_participants, all_splits, trip, trip_currency
    )

    # --- Settlement (from my perspective) ---
    settlement = _build_settlement(
        my_id, trip_currency,
        trip_settlements, other_settlements,
        all_splits, all_prepayments, participant_map,
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


# ---------------------------------------------------------------------------
# Helper: my cost
# ---------------------------------------------------------------------------

def _compute_my_cost(
    all_splits: list, my_id: int, trip_currency: str
) -> list[dict]:
    """
    Collect all my splits across all currencies + sum in main currency.
    Returns List[SimpleMoneyValueDto].
    """
    cost_by_currency: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total_in_trip_currency = ZERO

    for split in all_splits:
        if split.participant_id != my_id:
            continue
        expense_currency = split.expense.expense_currency.upper()
        cost_by_currency[expense_currency] += split.amount_in_cost_currency
        total_in_trip_currency += split.amount_in_trip_currency

    result = []

    # Main currency entry (sum of all, converted)
    result.append({
        "is_main_currency": True,
        "currency": trip_currency,
        "amount": float(total_in_trip_currency),
    })

    # Per-currency entries (non-main only)
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

        # total_expense: main currency + expense currency (if different)
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

        # shared_with
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
    """
    For each participant, totalExpenses = sum of their splits per currency + main currency total.
    """
    # Pre-aggregate splits per participant per currency
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
# Helper: build settlement (from my perspective)
# ---------------------------------------------------------------------------

def _build_settlement(
    my_id: int,
    trip_currency: str,
    trip_settlements: list,
    other_settlements: list,
    all_splits: list,
    all_prepayments: list,
    participant_map: dict,
) -> dict:
    """
    Build SettlementDto from the perspective of the logged-in user.

    For each other participant, compute:
      - left_for_settled: how much is left to settle (+ they owe me, - I owe them)
      - all_related_amount: total amount of all splits between us (+ / -)
      - prepayment: prepayment details between us
    """
    # Collect all participant IDs I have relations with
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

    # Also check splits and prepayments for relations
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

    relations = []
    for other_id in related_ids:
        relation = _build_single_relation(
            my_id, other_id, trip_currency,
            trip_settlements, other_settlements,
            all_splits, all_prepayments, participant_map,
        )
        relations.append(relation)

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


def _build_prepayment_details(
    my_id: int,
    other_id: int,
    trip_currency: str,
    all_prepayments: list,
) -> dict:
    """
    Build PrepaymentDetailsDto for the relation between my_id and other_id.

    amount_left: aggregate remaining prepayment balances per currency.
    history: all prepayment records between the two, with date and values.
    """
    amount_left_by_currency: dict[str, Decimal] = defaultdict(lambda: ZERO)
    history = []

    for prep in all_prepayments:
        is_from_me = (prep.from_participant_id == my_id and prep.to_participant_id == other_id)
        is_to_me = (prep.from_participant_id == other_id and prep.to_participant_id == my_id)

        if not is_from_me and not is_to_me:
            continue

        curr = prep.currency.upper()

        # amount_left tracking
        if prep.amount_left > ZERO:
            if is_from_me:
                # I prepaid to them → positive (they have my money)
                amount_left_by_currency[curr] += prep.amount_left
            else:
                # They prepaid to me → negative (I have their money)
                amount_left_by_currency[curr] -= prep.amount_left

        # History entry (always show full amount, sign indicates direction)
        sign = Decimal("1") if is_from_me else Decimal("-1")
        history.append({
            "date": prep.created_date.timestamp() * 1000,
            "values": {
                "is_main_currency": curr == trip_currency,
                "currency": curr,
                "amount": float(sign * prep.amount),
            },
        })

    # Build amount_left list
    amount_left = []
    for curr, amt in amount_left_by_currency.items():
        amount_left.append({
            "is_main_currency": curr == trip_currency,
            "currency": curr,
            "amount": float(amt),
        })

    return {
        "amount_left": amount_left,
        "history": history,
    }


# ---------------------------------------------------------------------------
# Create trip (existing, unchanged logic)
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