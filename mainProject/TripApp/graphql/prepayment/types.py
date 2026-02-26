import strawberry
from typing import Optional


@strawberry.type
class PrepaymentType:
    id: int
    from_participant_id: int
    from_nickname: str
    to_participant_id: int
    to_nickname: str
    amount: float
    amount_left: float
    currency: str
    created_date: str


@strawberry.type
class PrepaymentPayload:
    success: bool
    message: str
    prepayment: Optional[PrepaymentType] = None