"""
Reconciliation engine — FIFO auto-settlement of prepayments against splits,
and cross-settlement of opposing splits.

Called from:
  - addExpense  (after creating splits, try to apply existing prepayments + cross-settle)
  - addPrepayment (after creating prepayment, try to apply against existing splits)
"""

from decimal import Decimal
from asgiref.sync import sync_to_async
from TripApp.models import Prepayment, Split, Expense, Trip


ZERO = Decimal("0.00")


def _min_positive(*values: Decimal) -> Decimal:
    return min(v for v in values if v > ZERO)


def _update_is_settlement(split: Split) -> None:
    """Set is_settlement flag based on remaining amounts."""
    split.is_settlement = (
        split.left_to_settlement_amount_in_trip_currency <= ZERO
        and split.left_to_settlement_amount_in_cost_currency <= ZERO
    )


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
    rate = expense.rate

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

        if prep_currency == trip_currency:
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

        elif prep_currency == expense_currency and expense_currency != trip_currency:
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

        else:
            continue

        await sync_to_async(prepayment.save)()

    _update_is_settlement(split)
    await sync_to_async(split.save)()


async def apply_prepayment_to_splits(prepayment: Prepayment, trip: Trip) -> None:
    """
    Try to settle existing unsettled splits using a new prepayment (FIFO by expense created_at).

    Called after a new prepayment is created.
    """
    if prepayment.amount_left <= ZERO:
        return

    prep_currency = prepayment.currency.upper()
    trip_currency = trip.default_currency.upper()

    from_id = await sync_to_async(lambda: prepayment.from_participant_id)()
    to_id = await sync_to_async(lambda: prepayment.to_participant_id)()

    base_qs = Split.objects.filter(
        participant_id=from_id,
        expense__payer_id=to_id,
        expense__trip=trip,
        is_settlement=False,
        left_to_settlement_amount_in_trip_currency__gt=ZERO,
    ).select_related("expense").order_by("expense__created_at")

    if prep_currency != trip_currency:
        base_qs = base_qs.filter(expense__expense_currency__iexact=prep_currency)

    splits = await sync_to_async(lambda: list(base_qs))()

    for split in splits:
        if prepayment.amount_left <= ZERO:
            break

        expense = split.expense
        expense_currency = expense.expense_currency.upper()
        rate = expense.rate

        if prep_currency == trip_currency:
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

        _update_is_settlement(split)
        await sync_to_async(split.save)()

    await sync_to_async(prepayment.save)()


async def cross_settle_split(split: Split, trip: Trip) -> None:
    """
    Cross-settle a new split against existing opposing splits (FIFO by expense created_at).

    Called after a new expense is created — for each split where participant != payer.

    If P1 paid and P2 has a split (P2 owes P1), we look for existing splits where
    P1 owes P2 (P2 paid, P1 has split) and settle them against each other.

    Currency rules:
      - Expense in trip currency → cross-settle only against splits in trip currency
        (work in trip currency)
      - Expense in other currency → cross-settle only against splits in same currency
        (work in cost currency)
    """
    if split.left_to_settlement_amount_in_trip_currency <= ZERO:
        return

    expense = await sync_to_async(lambda: split.expense)()
    payer_id = await sync_to_async(lambda: expense.payer_id)()
    participant_id = await sync_to_async(lambda: split.participant_id)()
    expense_currency = expense.expense_currency.upper()
    trip_currency = trip.default_currency.upper()
    new_rate = expense.rate

    # New split: participant owes payer
    # Look for opposing: payer owes participant (payer has split, participant paid)
    base_qs = Split.objects.filter(
        participant_id=payer_id,
        expense__payer_id=participant_id,
        expense__trip=trip,
        is_settlement=False,
        left_to_settlement_amount_in_trip_currency__gt=ZERO,
    ).select_related("expense").order_by("expense__created_at")

    # Currency matching
    if expense_currency == trip_currency:
        # Trip currency expense → only cross-settle with trip currency expenses
        base_qs = base_qs.filter(expense__expense_currency__iexact=trip_currency)
    else:
        # Other currency expense → only cross-settle with same currency expenses
        base_qs = base_qs.filter(expense__expense_currency__iexact=expense_currency)

    opposing_splits = await sync_to_async(lambda: list(base_qs))()

    for opposing in opposing_splits:
        if split.left_to_settlement_amount_in_trip_currency <= ZERO:
            break

        opposing_expense = opposing.expense
        opposing_rate = opposing_expense.rate

        if expense_currency == trip_currency:
            # Both in trip currency — settle in trip currency
            settleable_trip = _min_positive(
                split.left_to_settlement_amount_in_trip_currency,
                opposing.left_to_settlement_amount_in_trip_currency,
            )

            # Deduct from new split
            split.left_to_settlement_amount_in_trip_currency -= settleable_trip
            if new_rate and new_rate != ZERO:
                settleable_new_cost = (settleable_trip / new_rate).quantize(Decimal("0.01"))
            else:
                settleable_new_cost = settleable_trip
            split.left_to_settlement_amount_in_cost_currency = max(
                ZERO,
                split.left_to_settlement_amount_in_cost_currency - settleable_new_cost,
            )

            # Deduct from opposing split
            opposing.left_to_settlement_amount_in_trip_currency -= settleable_trip
            if opposing_rate and opposing_rate != ZERO:
                settleable_opp_cost = (settleable_trip / opposing_rate).quantize(Decimal("0.01"))
            else:
                settleable_opp_cost = settleable_trip
            opposing.left_to_settlement_amount_in_cost_currency = max(
                ZERO,
                opposing.left_to_settlement_amount_in_cost_currency - settleable_opp_cost,
            )

        else:
            # Both in same non-trip currency — settle in cost currency
            settleable_cost = _min_positive(
                split.left_to_settlement_amount_in_cost_currency,
                opposing.left_to_settlement_amount_in_cost_currency,
            )

            # Deduct from new split
            split.left_to_settlement_amount_in_cost_currency -= settleable_cost
            settleable_new_trip = (settleable_cost * new_rate).quantize(Decimal("0.01"))
            split.left_to_settlement_amount_in_trip_currency = max(
                ZERO,
                split.left_to_settlement_amount_in_trip_currency - settleable_new_trip,
            )

            # Deduct from opposing split
            opposing.left_to_settlement_amount_in_cost_currency -= settleable_cost
            settleable_opp_trip = (settleable_cost * opposing_rate).quantize(Decimal("0.01"))
            opposing.left_to_settlement_amount_in_trip_currency = max(
                ZERO,
                opposing.left_to_settlement_amount_in_trip_currency - settleable_opp_trip,
            )

        _update_is_settlement(opposing)
        await sync_to_async(opposing.save)()

    _update_is_settlement(split)
    await sync_to_async(split.save)()