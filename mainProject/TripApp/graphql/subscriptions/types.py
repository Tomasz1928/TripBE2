import strawberry
from enum import Enum


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
class TripNotification:
    trip_id: int
    trip_name: str
    event_type: TripEventType
    actor_nickname: str
    actor_participant_id: int