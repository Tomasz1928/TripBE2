"""
Reconciliation engine — FIFO auto-settlement of prepayments against splits.

Called from:
  - addExpense  (after creating splits, try to apply existing prepayments)
  - addPrepayment (after creating prepayment, try to apply against existing splits)
"""

from decimal import Decimal
from asgiref.sync import sync_to_async
from TripApp.models import Prepayment, Split, Expense, Trip


ZERO = Decimal("0.00")


def _min_positive(*values: Decimal) -> Decimal:
    return min(v for v in values if v > ZERO)


async def apply_prepayments_to_split(split: Split, trip: Trip) -> None:
    """
    Try to settle a single split using available prepayments (FIFO by created_date).

    Called after a new expense is created — for each split where participant != payer.

    Prepayment matching rules:
      - from_participant = split.participant (the one who owes)
      - to_participant   = expense.payer     (the one who paid)
      - Prepayment in trip currency  → can settle splits in ANY currency
      - Prepayment in other currency → can only settle splits in THAT currency
    """
    if split.left_to_settlement_amount_in_trip_currency <= ZERO:
        return

    expense = await sync_to_async(lambda: split.expense)()
    payer_id = await sync_to_async(lambda: expense.payer_id)()
    participant_id = await sync_to_async(lambda: split.participant_id)()
    expense_currency = expense.expense_currency.upper()
    trip_currency = trip.default_currency.upper()
    rate = expense.rate  # expense_currency → trip_currency

    # Find prepayments from this participant to the payer, with remaining balance
    prepayments = await sync_to_async(
        lambda: list(
            Prepayment.objects.filter(
                trip=trip,
                from_participant_id=participant_id,
                to_participant_id=payer_id,
                amount_left__gt=ZERO,
            ).order_by("created_date")
        )
    )()

    for prepayment in prepayments:
        if split.left_to_settlement_amount_in_trip_currency <= ZERO:
            break

        prep_currency = prepayment.currency.upper()

        # Check currency compatibility
        if prep_currency == trip_currency:
            # Trip-currency prepayment → can settle anything
            # Work in trip currency
            settleable_trip = _min_positive(
                prepayment.amount_left,
                split.left_to_settlement_amount_in_trip_currency,
            )

            # Deduct from prepayment (in trip currency)
            prepayment.amount_left -= settleable_trip

            # Deduct from split
            split.left_to_settlement_amount_in_trip_currency -= settleable_trip

            # Convert to cost currency using expense rate
            if rate and rate != ZERO:
                settleable_cost = (settleable_trip / rate).quantize(Decimal("0.01"))
            else:
                settleable_cost = settleable_trip

            split.left_to_settlement_amount_in_cost_currency = max(
                ZERO,
                split.left_to_settlement_amount_in_cost_currency - settleable_cost,
            )

        elif prep_currency == expense_currency and expense_currency != trip_currency:
            # Other-currency prepayment → can only settle splits in same currency
            # Work in cost (expense) currency
            settleable_cost = _min_positive(
                prepayment.amount_left,
                split.left_to_settlement_amount_in_cost_currency,
            )

            # Deduct from prepayment (in expense currency)
            prepayment.amount_left -= settleable_cost

            # Deduct from split in cost currency
            split.left_to_settlement_amount_in_cost_currency -= settleable_cost

            # Convert to trip currency
            settleable_trip = (settleable_cost * rate).quantize(Decimal("0.01"))
            split.left_to_settlement_amount_in_trip_currency = max(
                ZERO,
                split.left_to_settlement_amount_in_trip_currency - settleable_trip,
            )

        else:
            # Currency mismatch — skip this prepayment
            continue

        await sync_to_async(prepayment.save)()

    await sync_to_async(split.save)()


async def apply_prepayment_to_splits(prepayment: Prepayment, trip: Trip) -> None:
    """
    Try to settle existing unsettled splits using a new prepayment (FIFO by expense created_at).

    Called after a new prepayment is created.

    Matching rules:
      - split.participant = prepayment.from_participant (the one who owes)
      - expense.payer     = prepayment.to_participant   (the one who paid)
      - Prepayment in trip currency  → can settle splits in ANY currency
      - Prepayment in other currency → can only settle splits in THAT currency
    """
    if prepayment.amount_left <= ZERO:
        return

    prep_currency = prepayment.currency.upper()
    trip_currency = trip.default_currency.upper()

    from_id = await sync_to_async(lambda: prepayment.from_participant_id)()
    to_id = await sync_to_async(lambda: prepayment.to_participant_id)()

    # Base filter: unsettled splits for this participant where the payer is to_participant
    base_qs = Split.objects.filter(
        participant_id=from_id,
        expense__payer_id=to_id,
        expense__trip=trip,
        left_to_settlement_amount_in_trip_currency__gt=ZERO,
    ).select_related("expense").order_by("expense__created_at")

    # Currency filtering
    if prep_currency != trip_currency:
        # Other-currency prepayment → only settle splits with matching expense currency
        base_qs = base_qs.filter(expense__expense_currency__iexact=prep_currency)

    splits = await sync_to_async(lambda: list(base_qs))()

    for split in splits:
        if prepayment.amount_left <= ZERO:
            break

        expense = split.expense  # already fetched via select_related
        expense_currency = expense.expense_currency.upper()
        rate = expense.rate

        if prep_currency == trip_currency:
            # Trip-currency prepayment — work in trip currency
            settleable_trip = _min_positive(
                prepayment.amount_left,
                split.left_to_settlement_amount_in_trip_currency,
            )

            prepayment.amount_left -= settleable_trip
            split.left_to_settlement_amount_in_trip_currency -= settleable_trip

            if rate and rate != ZERO:
                settleable_cost = (settleable_trip / rate).quantize(Decimal("0.01"))
            else:
                settleable_cost = settleable_trip

            split.left_to_settlement_amount_in_cost_currency = max(
                ZERO,
                split.left_to_settlement_amount_in_cost_currency - settleable_cost,
            )

        else:
            # Other-currency prepayment — work in cost currency
            settleable_cost = _min_positive(
                prepayment.amount_left,
                split.left_to_settlement_amount_in_cost_currency,
            )

            prepayment.amount_left -= settleable_cost
            split.left_to_settlement_amount_in_cost_currency -= settleable_cost

            settleable_trip = (settleable_cost * rate).quantize(Decimal("0.01"))
            split.left_to_settlement_amount_in_trip_currency = max(
                ZERO,
                split.left_to_settlement_amount_in_trip_currency - settleable_trip,
            )

        await sync_to_async(split.save)()

    await sync_to_async(prepayment.save)()