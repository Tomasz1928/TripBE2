import strawberry
from typing import Optional, List
from enum import Enum


# --- Shared ---

@strawberry.type
class SimpleMoneyValueType:
    is_main_currency: bool
    currency: str
    amount: float


# --- Trip List (lightweight) ---

@strawberry.type
class TripListItemType:
    id: int
    title: str
    date_start: float  # timestamp ms
    date_end: float
    currency: str
    description: str
    total_expenses: float
    im_owner: bool


@strawberry.type
class TripListType:
    trips: List[TripListItemType]


# --- Categories ---

@strawberry.type
class CategoryType:
    category_id: int
    total_amount: float


# --- Expenses ---

@strawberry.type
class ShareType:
    participant_id: int
    participant_nickname: str
    split_value: List[SimpleMoneyValueType]
    is_settlement: bool
    left_for_settlement: List[SimpleMoneyValueType]


@strawberry.type
class ExpenseDetailType:
    id: int
    name: str
    description: str
    total_expense: List[SimpleMoneyValueType]
    amount: float
    currency: str
    date: float  # timestamp ms
    category_id: int
    payer_id: int
    payer_nickname: str
    shared_with: List[ShareType]


# --- Participants ---

@strawberry.type
class ParticipantDetailType:
    id: int
    nickname: str
    total_expenses: List[SimpleMoneyValueType]
    is_owner: bool
    is_placeholder: bool
    access_code: Optional[str]
    is_active: bool


# --- Settlement ---

@strawberry.type
class PrepaymentHistoryType:
    date: float  # timestamp ms
    values: SimpleMoneyValueType


@strawberry.type
class PrepaymentDetailsType:
    amount_left: List[SimpleMoneyValueType]
    history: List[PrepaymentHistoryType]


@strawberry.type
class SettlementRelationType:
    related_id: int
    related_name: str
    left_for_settled: List[SimpleMoneyValueType]
    all_related_amount: List[SimpleMoneyValueType]
    prepayment: PrepaymentDetailsType


@strawberry.type
class SettlementType:
    relations: List[SettlementRelationType]


# --- Settlement History ---

@strawberry.enum
class SettlementHistoryEventType(Enum):
    MANUAL_BY_AMOUNT = "MANUAL_BY_AMOUNT"
    MANUAL_BY_COSTS = "MANUAL_BY_COSTS"
    MANUAL_BY_PREPAYMENT = "MANUAL_BY_PREPAYMENT"
    AUTO_PREPAYMENT = "AUTO_PREPAYMENT"
    AUTO_CROSS_SETTLE = "AUTO_CROSS_SETTLE"


@strawberry.type
class SettlementHistoryType:
    id: int
    settlement_type: SettlementHistoryEventType
    actor_participant_id: Optional[int]
    actor_nickname: Optional[str]
    other_participant_id: int
    other_nickname: str
    amount_in_settlement_currency: float
    settlement_currency: str
    amount_in_trip_currency: float
    related_expense_ids: List[int]
    created_at: float  # timestamp ms


# --- Trip Details (full) ---

@strawberry.type
class TripDetailType:
    id: int
    title: str
    date_start: float
    date_end: float
    currency: str
    description: str
    total_expenses: float
    categories: List[CategoryType]
    owner_id: int
    im_owner: bool
    my_participant_id: int
    my_cost: List[SimpleMoneyValueType]
    expenses: List[ExpenseDetailType]
    participants: List[ParticipantDetailType]
    settlement: Optional[SettlementType]
    settlement_history: List[SettlementHistoryType]


# --- Payloads ---

@strawberry.type
class TripPayload:
    success: bool
    message: str
    trip: Optional[TripDetailType] = None