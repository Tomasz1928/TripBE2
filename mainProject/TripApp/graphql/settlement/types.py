import strawberry
from typing import List, Optional


@strawberry.type
class SettlementTripCurrencyType:
    from_participant_id: int
    from_nickname: str
    to_participant_id: int
    to_nickname: str
    amount: float
    currency: str


@strawberry.type
class SettlementOtherCurrencyType:
    from_participant_id: int
    from_nickname: str
    to_participant_id: int
    to_nickname: str
    amount: float
    currency: str


@strawberry.type
class TripSettlementsType:
    trip_currency_settlements: List[SettlementTripCurrencyType]
    other_currency_settlements: List[SettlementOtherCurrencyType]


# --- Settle by amount ---

@strawberry.type
class SettleByAmountPayload:
    success: bool
    message: str
    settled_amount: Optional[float] = None
    leftover_amount: Optional[float] = None
    prepayment_created: Optional[bool] = None


# --- Settle by costs ---

@strawberry.input
class SettleByCostsItem:
    expense_id: int
    participant_id: int


@strawberry.type
class SettleByCostsPayload:
    success: bool
    message: str
    settled_count: Optional[int] = None