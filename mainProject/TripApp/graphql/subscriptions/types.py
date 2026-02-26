import strawberry
from enum import Enum
from typing import Optional, List
from ..trip.types import (
    SimpleMoneyValueType,
    CategoryType,
    ExpenseDetailType,
    ParticipantDetailType,
    SettlementType,
)


@strawberry.enum
class TripEventType(Enum):
    EXPENSE_ADDED = "EXPENSE_ADDED"
    EXPENSE_UPDATED = "EXPENSE_UPDATED"
    EXPENSE_DELETED = "EXPENSE_DELETED"
    PREPAYMENT_ADDED = "PREPAYMENT_ADDED"
    SETTLEMENT_CHANGED = "SETTLEMENT_CHANGED"
    PARTICIPANT_ADDED = "PARTICIPANT_ADDED"
    PARTICIPANT_UPDATED = "PARTICIPANT_UPDATED"
    PARTICIPANT_REMOVED = "PARTICIPANT_REMOVED"


@strawberry.type
class TripDelta:
    trip_id: int
    event_type: TripEventType

    # Upserts
    expenses: Optional[List[ExpenseDetailType]] = None
    participants: Optional[List[ParticipantDetailType]] = None
    categories: Optional[List[CategoryType]] = None
    settlement: Optional[SettlementType] = None

    # Removes
    removed_expense_ids: Optional[List[int]] = None
    removed_participant_ids: Optional[List[int]] = None

    # Scalars (always sent when anything changes)
    total_expenses: Optional[float] = None
    my_cost: Optional[List[SimpleMoneyValueType]] = None