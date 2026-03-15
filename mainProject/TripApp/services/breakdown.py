"""
Helper for managing Split.settlement_breakdown.

Each entry: {"type": "<TYPE>", "amount_cost": float, "amount_trip": float}

Types:
  SELF             — payer's own split (set at creation)
  AUTO_PREPAYMENT  — auto-settled via prepayment reconciliation
  AUTO_CROSS_SETTLE — auto-settled via cross-settlement
  MANUAL_BY_AMOUNT — manually settled by amount
  MANUAL_BY_COSTS  — manually settled by marking costs
  UNSETTLED        — computed at read time, never stored

Aggregation: entries with the same type are merged (amounts summed)
to keep the JSON compact.
"""

from decimal import Decimal


def append_breakdown(split, settlement_type: str, amount_cost: Decimal, amount_trip: Decimal) -> None:
    """
    Append (or merge) a settlement entry into split.settlement_breakdown.

    Mutates split.settlement_breakdown in place. Caller is responsible for saving.
    """
    if amount_cost <= 0 and amount_trip <= 0:
        return

    breakdown = split.settlement_breakdown
    if not isinstance(breakdown, list):
        breakdown = []

    # Try to merge with existing entry of same type
    for entry in breakdown:
        if entry.get("type") == settlement_type:
            entry["amount_cost"] = float(
                Decimal(str(entry["amount_cost"])) + amount_cost
            )
            entry["amount_trip"] = float(
                Decimal(str(entry["amount_trip"])) + amount_trip
            )
            split.settlement_breakdown = breakdown
            return

    # New entry
    breakdown.append({
        "type": settlement_type,
        "amount_cost": float(amount_cost),
        "amount_trip": float(amount_trip),
    })
    split.settlement_breakdown = breakdown


def set_self_breakdown(split) -> None:
    """
    Set breakdown for a self-split (payer = participant).
    Replaces any existing breakdown.
    """
    split.settlement_breakdown = [{
        "type": "SELF",
        "amount_cost": float(split.amount_in_cost_currency),
        "amount_trip": float(split.amount_in_trip_currency),
    }]


def compute_unsettled_entry(split) -> dict | None:
    """
    Compute the UNSETTLED portion at read time.
    Returns a dict entry or None if fully settled.
    """
    left_cost = float(split.left_to_settlement_amount_in_cost_currency)
    left_trip = float(split.left_to_settlement_amount_in_trip_currency)

    if left_cost > 0.005 or left_trip > 0.005:
        return {
            "type": "UNSETTLED",
            "amount_cost": round(left_cost, 2),
            "amount_trip": round(left_trip, 2),
        }
    return None


def get_full_breakdown(split) -> list[dict]:
    """
    Return the full breakdown including UNSETTLED (computed).
    Used by the query layer.
    """
    breakdown = list(split.settlement_breakdown or [])

    unsettled = compute_unsettled_entry(split)
    if unsettled:
        breakdown.append(unsettled)

    return breakdown