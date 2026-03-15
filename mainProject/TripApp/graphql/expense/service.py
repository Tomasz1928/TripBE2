from datetime import datetime, timezone
from decimal import Decimal
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant, Expense, Split, Prepayment
from TripApp.services.reconciliation import apply_prepayments_to_split, cross_settle_split
from TripApp.services.exchange import get_exchange_rate
from ..settlement.service import recalculate_settlements
from TripApp.services.delta_builder import (
    build_expense_added_notification,
    build_expense_updated_notification,
    build_expense_deleted_notification,
)
from TripApp.services.actor_resolver import get_actor_participant_id
from TripApp.services.broadcast import broadcast_delta


ZERO = Decimal("0.00")


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _is_self_split(payer_id: int, participant_id: int) -> bool:
    return payer_id == participant_id


async def _verify_payer_is_caller(request: HttpRequest, expense: Expense) -> bool:
    """Check that the logged-in user is the payer of this expense."""
    user = await sync_to_async(lambda: request.user)()
    payer_user_id = expense.payer.user_id
    return payer_user_id == user.id


def _compute_split_amounts(share: dict, trip_currency: str, rate: Decimal) -> tuple[Decimal, Decimal]:
    """Compute (split_amount_cost, split_amount_trip) from share's split_value list."""
    split_amount_cost = ZERO
    split_amount_trip = ZERO

    for money in share["split_value"]:
        amount = _to_decimal(money["amount"])
        money_currency = money["currency"].strip().upper()
        is_main = (money_currency == trip_currency)

        if is_main:
            split_amount_trip += amount
            if rate != ZERO:
                split_amount_cost += (amount / rate).quantize(Decimal("0.01"))
        else:
            split_amount_cost += amount
            split_amount_trip += (amount * rate).quantize(Decimal("0.01"))

    return split_amount_cost, split_amount_trip


# ---------------------------------------------------------------------------
# Add Expense
# ---------------------------------------------------------------------------

async def add_expense(request: HttpRequest, data: dict) -> dict:
    trip_id = data["trip_id"]
    trip = await sync_to_async(Trip.objects.select_related("trip_owner").get)(trip_id=trip_id)

    participant_ids = [s["participant_id"] for s in data["shared_with"]]
    participant_ids.append(data["payer_id"])
    participants = await sync_to_async(
        lambda: {
            p.participant_id: p
            for p in Participant.objects.filter(
                participant_id__in=participant_ids, trip=trip
            )
        }
    )()

    payer = participants[data["payer_id"]]

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

    splits_to_create = []
    splits_needing_reconciliation_indices = []

    for idx, share in enumerate(data["shared_with"]):
        participant = participants[share["participant_id"]]

        split_amount_cost, split_amount_trip = _compute_split_amounts(
            share, trip_currency, rate
        )
        is_self = _is_self_split(payer.participant_id, participant.participant_id)

        split = Split(
            participant=participant,
            expense=expense,
            is_settlement=is_self,
            amount_in_cost_currency=split_amount_cost,
            amount_in_trip_currency=split_amount_trip,
            left_to_settlement_amount_in_cost_currency=ZERO if is_self else split_amount_cost,
            left_to_settlement_amount_in_trip_currency=ZERO if is_self else split_amount_trip,
        )
        splits_to_create.append(split)

        if not is_self:
            splits_needing_reconciliation_indices.append(idx)

    created_splits = await sync_to_async(
        lambda: Split.objects.bulk_create(splits_to_create)
    )()
    for idx in splits_needing_reconciliation_indices:
        split = created_splits[idx]
        await apply_prepayments_to_split(split, trip)
        await cross_settle_split(split, trip)

    await recalculate_settlements(trip)

    # Broadcast delta
    actor_id = await get_actor_participant_id(request, trip)
    notification = await build_expense_added_notification(trip, actor_id)
    await broadcast_delta(trip.trip_id, notification)

    return {"success": True, "message": "Expense added successfully."}


# ---------------------------------------------------------------------------
# Update Expense
# ---------------------------------------------------------------------------

async def update_expense(request: HttpRequest, data: dict) -> dict:
    expense_id = data["expense_id"]
    trip_id = data["trip_id"]

    trip = await sync_to_async(Trip.objects.select_related("trip_owner").get)(trip_id=trip_id)
    expense = await sync_to_async(Expense.objects.select_related("payer").get)(
        expense_id=expense_id, trip=trip
    )

    if not await _verify_payer_is_caller(request, expense):
        return {"success": False, "message": "Only the payer can edit this expense."}

    trip_currency = trip.default_currency.upper()

    # Step 1: Collect old state
    old_splits = await sync_to_async(
        lambda: list(Split.objects.filter(expense=expense))
    )()

    old_payer_id = expense.payer_id
    old_expense_currency = expense.expense_currency.upper()

    old_settled_cost: dict[int, Decimal] = {}
    for old_split in old_splits:
        pid = old_split.participant_id
        if pid == old_payer_id:
            continue
        settled_cost = old_split.amount_in_cost_currency - old_split.left_to_settlement_amount_in_cost_currency
        old_settled_cost[pid] = max(ZERO, settled_cost)

    # Step 2: Delete old splits
    await sync_to_async(Split.objects.filter(expense=expense).delete)()

    # Step 3: Update expense fields
    expense_currency = data["currency"].strip().upper()
    rate = await get_exchange_rate(expense_currency, trip_currency)

    amount_in_expense_currency = _to_decimal(data["amount"])
    amount_in_trip_currency = (amount_in_expense_currency * rate).quantize(Decimal("0.01"))

    expense.title = data["name"].strip()
    expense.description = data.get("description", "").strip()
    expense.category = data["category_id"]
    expense.expense_currency = expense_currency
    expense.amount_in_expenses_currency = amount_in_expense_currency
    expense.amount_in_trip_currency = amount_in_trip_currency
    expense.rate = rate
    expense.created_at = datetime.fromtimestamp(data["date"] / 1000, tz=timezone.utc)

    participant_ids = [s["participant_id"] for s in data["shared_with"]]
    participant_ids.append(data["payer_id"])
    if old_payer_id not in participant_ids:
        participant_ids.append(old_payer_id)
    participants = await sync_to_async(
        lambda: {
            p.participant_id: p
            for p in Participant.objects.filter(
                participant_id__in=participant_ids, trip=trip
            )
        }
    )()

    new_payer = participants[data["payer_id"]]
    expense.payer = new_payer
    await sync_to_async(expense.save)()

    payer_changed = (old_payer_id != new_payer.participant_id)

    # Step 4: If payer changed, all old settled amounts become prepayments to OLD payer
    if payer_changed:
        old_payer = participants[old_payer_id]
        prepayments_to_create = []
        for pid, settled_cost in old_settled_cost.items():
            if settled_cost > ZERO:
                participant = participants[pid]
                prepayments_to_create.append(Prepayment(
                    trip=trip,
                    from_participant=participant,
                    to_participant=old_payer,
                    amount=settled_cost,
                    amount_left=settled_cost,
                    currency=old_expense_currency,
                ))
        if prepayments_to_create:
            await sync_to_async(
                lambda: Prepayment.objects.bulk_create(prepayments_to_create)
            )()
        old_settled_cost = {}

    # Step 5: Create new splits
    splits_to_create = []
    splits_needing_reconciliation_indices = []
    overpaid_prepayments = []

    for idx, share in enumerate(data["shared_with"]):
        participant = participants[share["participant_id"]]

        new_cost, new_trip = _compute_split_amounts(share, trip_currency, rate)
        is_self = _is_self_split(new_payer.participant_id, participant.participant_id)

        if is_self:
            left_cost = ZERO
            left_trip = ZERO
        else:
            prev_settled_cost = old_settled_cost.get(participant.participant_id, ZERO)

            if prev_settled_cost > new_cost:
                overpaid_cost = prev_settled_cost - new_cost
                overpaid_prepayments.append(Prepayment(
                    trip=trip,
                    from_participant=participant,
                    to_participant=new_payer,
                    amount=overpaid_cost,
                    amount_left=overpaid_cost,
                    currency=expense_currency,
                    rate=rate,
                ))
                left_cost = ZERO
                left_trip = ZERO
            else:
                left_cost = new_cost - prev_settled_cost
                if new_cost > ZERO:
                    ratio = left_cost / new_cost
                    left_trip = (new_trip * ratio).quantize(Decimal("0.01"))
                else:
                    left_trip = ZERO

        is_settled = is_self or (left_cost <= ZERO and left_trip <= ZERO)

        split = Split(
            participant=participant,
            expense=expense,
            is_settlement=is_settled,
            amount_in_cost_currency=new_cost,
            amount_in_trip_currency=new_trip,
            left_to_settlement_amount_in_cost_currency=left_cost,
            left_to_settlement_amount_in_trip_currency=left_trip,
        )
        splits_to_create.append(split)

        if not is_self and left_cost > ZERO:
            splits_needing_reconciliation_indices.append(idx)

    if overpaid_prepayments:
        await sync_to_async(
            lambda: Prepayment.objects.bulk_create(overpaid_prepayments)
        )()

    created_splits = await sync_to_async(
        lambda: Split.objects.bulk_create(splits_to_create)
    )()

    # Step 6: Auto-reconcile
    for idx in splits_needing_reconciliation_indices:
        split = created_splits[idx]
        await apply_prepayments_to_split(split, trip)
        await cross_settle_split(split, trip)

    # Step 7: Recalculate settlements
    await recalculate_settlements(trip)

    # Broadcast delta
    actor_id = await get_actor_participant_id(request, trip)
    notification = await build_expense_updated_notification(trip, actor_id)
    await broadcast_delta(trip.trip_id, notification)

    return {"success": True, "message": "Expense updated successfully."}


# ---------------------------------------------------------------------------
# Delete Expense
# ---------------------------------------------------------------------------

async def delete_expense(request: HttpRequest, trip_id: int, expense_id: int) -> dict:
    trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)
    expense = await sync_to_async(Expense.objects.select_related("payer").get)(
        expense_id=expense_id, trip=trip
    )

    if not await _verify_payer_is_caller(request, expense):
        return {"success": False, "message": "Only the payer can delete this expense."}

    expense_currency = expense.expense_currency.upper()
    payer = expense.payer

    splits = await sync_to_async(
        lambda: list(Split.objects.filter(expense=expense).select_related("participant"))
    )()

    prepayments_to_create = []
    for split in splits:
        if split.participant_id == payer.participant_id:
            continue

        settled_cost = split.amount_in_cost_currency - split.left_to_settlement_amount_in_cost_currency

        if settled_cost > ZERO:
            prepayments_to_create.append(Prepayment(
                trip=trip,
                from_participant=split.participant,
                to_participant=payer,
                amount=settled_cost,
                amount_left=settled_cost,
                currency=expense_currency,
                rate=expense.rate,
            ))

    if prepayments_to_create:
        await sync_to_async(
            lambda: Prepayment.objects.bulk_create(prepayments_to_create)
        )()

    await sync_to_async(expense.delete)()
    await recalculate_settlements(trip)

    # Broadcast delta
    actor_id = await get_actor_participant_id(request, trip)
    notification = await build_expense_deleted_notification(trip, actor_id)
    await broadcast_delta(trip.trip_id, notification)

    return {"success": True, "message": "Expense deleted successfully."}