"""
Settlement history logger — append-only log of settlement events.

Convention: participant_a.id < participant_b.id (same as ParticipantRelation).
"""

from decimal import Decimal
from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant, SettlementHistory


def _ordered_pair(id_a: int, id_b: int) -> tuple[int, int]:
    return (min(id_a, id_b), max(id_a, id_b))


async def log_settlement(
    trip: Trip,
    from_participant_id: int,
    to_participant_id: int,
    settlement_type: str,
    amount_in_settlement_currency: Decimal,
    settlement_currency: str,
    amount_in_trip_currency: Decimal,
    related_expense_ids: list[int] | None = None,
    actor_participant_id: int | None = None,
) -> None:
    """
    Log a settlement event to SettlementHistory.

    from_participant_id: the one whose debt is being reduced
    to_participant_id: the one being paid
    """
    a_id, b_id = _ordered_pair(from_participant_id, to_participant_id)

    await sync_to_async(SettlementHistory.objects.create)(
        trip=trip,
        participant_a_id=a_id,
        participant_b_id=b_id,
        settlement_type=settlement_type,
        actor_participant_id=actor_participant_id,
        amount_in_settlement_currency=amount_in_settlement_currency,
        settlement_currency=settlement_currency,
        amount_in_trip_currency=amount_in_trip_currency,
        related_expenses=related_expense_ids or [],
    )