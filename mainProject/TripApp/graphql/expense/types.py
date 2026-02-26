import strawberry
from typing import Optional, List


@strawberry.input
class SimpleMoneyValueInput:
    currency: str
    amount: float


@strawberry.input
class ShareInput:
    participant_id: int
    split_value: List[SimpleMoneyValueInput]


@strawberry.input
class AddExpenseInput:
    trip_id: int
    name: str
    description: str = ""
    amount: float
    currency: str
    category_id: int
    date: float  # timestamp in ms
    payer_id: int
    shared_with: List[ShareInput]


@strawberry.input
class UpdateExpenseInput:
    expense_id: int
    trip_id: int
    name: str
    description: str = ""
    amount: float
    currency: str
    category_id: int
    date: float  # timestamp in ms
    payer_id: int
    shared_with: List[ShareInput]


@strawberry.type
class SplitType:
    participant_id: int
    participant_nickname: str
    amount_in_cost_currency: float
    amount_in_trip_currency: float


@strawberry.type
class ExpenseType:
    expense_id: int
    title: str
    description: str
    category: int
    expense_currency: str
    amount_in_expenses_currency: float
    amount_in_trip_currency: float
    rate: float
    payer_id: int
    created_at: str
    splits: List[SplitType]


@strawberry.type
class ExpensePayload:
    success: bool
    message: str
    expense: Optional[ExpenseType] = None


@strawberry.type
class DeleteExpensePayload:
    success: bool
    message: str