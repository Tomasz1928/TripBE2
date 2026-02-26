from datetime import datetime, timezone
from decimal import Decimal
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant, Expense, Split, Prepayment
from TripApp.services.reconciliation import apply_prepayments_to_split
from ..settlement.service import recalculate_settlements


ZERO = Decimal("0.00")


async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """
    Placeholder: returns 1:1 rate.
    TODO: fetch real rate from external API
    """
    if from_currency.upper() == to_currency.upper():
        return Decimal("1.000000")
    return Decimal("1.000000")


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _is_settlement(payer_id: int, participant_id: int) -> bool:
    return payer_id == participant_id


async def _verify_payer_is_caller(request: HttpRequest, expense: Expense) -> bool:
    """Check that the logged-in user is the payer of this expense."""
    user = await sync_to_async(lambda: request.user)()
    payer = await sync_to_async(lambda: expense.payer)()
    payer_user_id = await sync_to_async(lambda: payer.user_id)()
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


def _build_splits_response(splits_data: list[dict]) -> list[dict]:
    return [
        {
            "participant_id": s["participant_id"],
            "participant_nickname": s["participant_nickname"],
            "amount_in_cost_currency": float(s["amount_in_cost_currency"]),
            "amount_in_trip_currency": float(s["amount_in_trip_currency"]),
        }
        for s in splits_data
    ]


# ---------------------------------------------------------------------------
# Add Expense
# ---------------------------------------------------------------------------

async def add_expense(request: HttpRequest, data: dict) -> dict:
    trip_id = data["trip_id"]
    trip = await sync_to_async(Trip.objects.select_related("trip_owner").get)(trip_id=trip_id)

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
    splits_to_reconcile = []

    for share in data["shared_with"]:
        participant = await sync_to_async(Participant.objects.get)(
            participant_id=share["participant_id"], trip=trip
        )

        split_amount_cost, split_amount_trip = _compute_split_amounts(
            share, trip_currency, rate
        )
        is_settled = _is_settlement(payer.participant_id, participant.participant_id)

        split = await sync_to_async(Split.objects.create)(
            participant=participant,
            expense=expense,
            is_settlement=is_settled,
            amount_in_cost_currency=split_amount_cost,
            amount_in_trip_currency=split_amount_trip,
            left_to_settlement_amount_in_cost_currency=ZERO if is_settled else split_amount_cost,
            left_to_settlement_amount_in_trip_currency=ZERO if is_settled else split_amount_trip,
        )

        if not is_settled:
            splits_to_reconcile.append(split)

        splits.append({
            "participant_id": participant.participant_id,
            "participant_nickname": participant.nickname,
            "amount_in_cost_currency": split_amount_cost,
            "amount_in_trip_currency": split_amount_trip,
        })

    for split in splits_to_reconcile:
        await apply_prepayments_to_split(split, trip)

    await recalculate_settlements(trip)

    return {
        "success": True,
        "message": "Expense added successfully.",
        "expense": expense,
        "splits": _build_splits_response(splits),
    }


# ---------------------------------------------------------------------------
# Update Expense
# ---------------------------------------------------------------------------

async def update_expense(request: HttpRequest, data: dict) -> dict:
    """
    Update an existing expense. Only the payer can edit.

    Logic for partial settlements:
      1. Collect how much was already settled per participant on old splits
         (settled = amount - left_to_settlement, in cost currency).
      2. Delete old splits.
      3. Create new splits with new amounts.
      4. For each new split, compare settled_old vs new_amount:
         - settled_old > new_amount → overpaid: create Prepayment for difference (in expense currency)
         - settled_old <= new_amount → left_to_settlement = new_amount - settled_old
      5. Auto-reconcile remaining with existing prepayments.
      6. Recalculate settlements.
    """
    expense_id = data["expense_id"]
    trip_id = data["trip_id"]

    trip = await sync_to_async(Trip.objects.select_related("trip_owner").get)(trip_id=trip_id)
    expense = await sync_to_async(Expense.objects.select_related("payer").get)(
        expense_id=expense_id, trip=trip
    )

    # Auth: only payer can edit
    if not await _verify_payer_is_caller(request, expense):
        return {"success": False, "message": "Only the payer can edit this expense."}

    trip_currency = trip.default_currency.upper()

    # --- Step 1: Collect old settlement amounts per participant ---
    old_splits = await sync_to_async(
        lambda: list(Split.objects.filter(expense=expense))
    )()

    # Map participant_id → how much was already settled in cost currency
    old_settled_cost: dict[int, Decimal] = {}
    old_settled_trip: dict[int, Decimal] = {}

    for old_split in old_splits:
        pid = old_split.participant_id
        settled_cost = old_split.amount_in_cost_currency - old_split.left_to_settlement_amount_in_cost_currency
        settled_trip = old_split.amount_in_trip_currency - old_split.left_to_settlement_amount_in_trip_currency
        old_settled_cost[pid] = max(ZERO, settled_cost)
        old_settled_trip[pid] = max(ZERO, settled_trip)

    # --- Step 2: Delete old splits ---
    await sync_to_async(Split.objects.filter(expense=expense).delete)()

    # --- Update expense fields ---
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

    # Update payer if changed
    new_payer = await sync_to_async(Participant.objects.get)(
        participant_id=data["payer_id"], trip=trip
    )
    expense.payer = new_payer
    await sync_to_async(expense.save)()

    # --- Step 3 & 4: Create new splits with settlement awareness ---
    splits = []
    splits_to_reconcile = []

    for share in data["shared_with"]:
        participant = await sync_to_async(Participant.objects.get)(
            participant_id=share["participant_id"], trip=trip
        )

        new_cost, new_trip = _compute_split_amounts(share, trip_currency, rate)
        is_settled = _is_settlement(new_payer.participant_id, participant.participant_id)

        if is_settled:
            left_cost = ZERO
            left_trip = ZERO
        else:
            # How much was previously settled for this participant
            prev_settled_cost = old_settled_cost.get(participant.participant_id, ZERO)

            if prev_settled_cost > new_cost:
                # Overpaid → create prepayment for the difference in expense currency
                overpaid_cost = prev_settled_cost - new_cost
                await sync_to_async(Prepayment.objects.create)(
                    trip=trip,
                    from_participant=participant,
                    to_participant=new_payer,
                    amount=overpaid_cost,
                    amount_left=overpaid_cost,
                    currency=expense_currency,
                )
                left_cost = ZERO
                left_trip = ZERO
            else:
                # Still owes: left = new - already_settled
                left_cost = new_cost - prev_settled_cost
                # Compute left_trip proportionally
                if new_cost > ZERO:
                    ratio = left_cost / new_cost
                    left_trip = (new_trip * ratio).quantize(Decimal("0.01"))
                else:
                    left_trip = ZERO

        split = await sync_to_async(Split.objects.create)(
            participant=participant,
            expense=expense,
            is_settlement=is_settled,
            amount_in_cost_currency=new_cost,
            amount_in_trip_currency=new_trip,
            left_to_settlement_amount_in_cost_currency=left_cost,
            left_to_settlement_amount_in_trip_currency=left_trip,
        )

        if not is_settled and left_cost > ZERO:
            splits_to_reconcile.append(split)

        splits.append({
            "participant_id": participant.participant_id,
            "participant_nickname": participant.nickname,
            "amount_in_cost_currency": new_cost,
            "amount_in_trip_currency": new_trip,
        })

    # --- Step 5: Auto-reconcile ---
    for split in splits_to_reconcile:
        await apply_prepayments_to_split(split, trip)

    # --- Step 6: Recalculate settlements ---
    await recalculate_settlements(trip)

    return {
        "success": True,
        "message": "Expense updated successfully.",
        "expense": expense,
        "splits": _build_splits_response(splits),
    }


# ---------------------------------------------------------------------------
# Delete Expense
# ---------------------------------------------------------------------------

async def delete_expense(request: HttpRequest, trip_id: int, expense_id: int) -> dict:
    """
    Delete an expense. Only the payer can delete.

    For each split that was partially/fully settled:
      - Create a Prepayment (in expense currency) for the settled amount,
        so the participant doesn't lose what they already paid.
    """
    trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)
    expense = await sync_to_async(Expense.objects.select_related("payer").get)(
        expense_id=expense_id, trip=trip
    )

    # Auth: only payer can delete
    if not await _verify_payer_is_caller(request, expense):
        return {"success": False, "message": "Only the payer can delete this expense."}

    expense_currency = expense.expense_currency.upper()
    payer = await sync_to_async(lambda: expense.payer)()

    # Collect splits and create prepayments for settled amounts
    splits = await sync_to_async(
        lambda: list(Split.objects.filter(expense=expense).select_related("participant"))
    )()

    for split in splits:
        if split.is_settlement:
            continue  # payer's own split, nothing to refund

        settled_cost = split.amount_in_cost_currency - split.left_to_settlement_amount_in_cost_currency

        if settled_cost > ZERO:
            participant = split.participant
            await sync_to_async(Prepayment.objects.create)(
                trip=trip,
                from_participant=participant,
                to_participant=payer,
                amount=settled_cost,
                amount_left=settled_cost,
                currency=expense_currency,
            )

    # Delete expense (cascade deletes splits)
    await sync_to_async(expense.delete)()

    # Recalculate settlements
    await recalculate_settlements(trip)

    return {
        "success": True,
        "message": "Expense deleted successfully.",
    }