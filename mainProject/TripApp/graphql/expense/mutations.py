import strawberry
from strawberry.types import Info
from .types import (
    AddExpenseInput, UpdateExpenseInput,
    ExpensePayload, DeleteExpensePayload,
    ExpenseType, SplitType,
)
from ..utils import get_request
from . import service


def _to_expense_payload(result: dict) -> ExpensePayload:
    expense = result.get("expense")
    splits = result.get("splits", [])

    if not expense:
        return ExpensePayload(
            success=result["success"],
            message=result["message"],
        )

    return ExpensePayload(
        success=result["success"],
        message=result["message"],
        expense=ExpenseType(
            expense_id=expense.expense_id,
            title=expense.title,
            description=expense.description,
            category=expense.category,
            expense_currency=expense.expense_currency,
            amount_in_expenses_currency=float(expense.amount_in_expenses_currency),
            amount_in_trip_currency=float(expense.amount_in_trip_currency),
            rate=float(expense.rate),
            payer_id=expense.payer_id,
            created_at=expense.created_at.isoformat(),
            splits=[
                SplitType(
                    participant_id=s["participant_id"],
                    participant_nickname=s["participant_nickname"],
                    amount_in_cost_currency=s["amount_in_cost_currency"],
                    amount_in_trip_currency=s["amount_in_trip_currency"],
                )
                for s in splits
            ],
        ),
    )


def _input_to_dict(data) -> dict:
    """Convert AddExpenseInput or UpdateExpenseInput to a plain dict."""
    d = {
        "trip_id": data.trip_id,
        "name": data.name,
        "description": data.description,
        "amount": data.amount,
        "currency": data.currency,
        "category_id": data.category_id,
        "date": data.date,
        "payer_id": data.payer_id,
        "shared_with": [
            {
                "participant_id": s.participant_id,
                "split_value": [
                    {"currency": mv.currency, "amount": mv.amount}
                    for mv in s.split_value
                ],
            }
            for s in data.shared_with
        ],
    }
    if hasattr(data, "expense_id"):
        d["expense_id"] = data.expense_id
    return d


@strawberry.type
class ExpenseMutation:

    @strawberry.mutation
    async def add_expense(self, info: Info, data: AddExpenseInput) -> ExpensePayload:
        result = await service.add_expense(get_request(info), _input_to_dict(data))
        return _to_expense_payload(result)

    @strawberry.mutation
    async def update_expense(self, info: Info, data: UpdateExpenseInput) -> ExpensePayload:
        result = await service.update_expense(get_request(info), _input_to_dict(data))
        return _to_expense_payload(result)

    @strawberry.mutation
    async def delete_expense(self, info: Info, trip_id: int, expense_id: int) -> DeleteExpensePayload:
        result = await service.delete_expense(get_request(info), trip_id, expense_id)
        return DeleteExpensePayload(
            success=result["success"],
            message=result["message"],
        )