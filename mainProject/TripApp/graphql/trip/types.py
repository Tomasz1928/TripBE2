import strawberry
from typing import Optional, List


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


# --- Payloads ---

@strawberry.type
class TripPayload:
    success: bool
    message: str
    trip: Optional[TripDetailType] = None