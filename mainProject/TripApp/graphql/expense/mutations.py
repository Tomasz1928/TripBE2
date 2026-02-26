import strawberry
from strawberry.types import Info
from .types import AddExpenseInput, ExpensePayload, ExpenseType, SplitType
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


@strawberry.type
class ExpenseMutation:

    @strawberry.mutation
    async def add_expense(self, info: Info, data: AddExpenseInput) -> ExpensePayload:
        request = get_request(info)

        input_dict = {
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
                        {
                            "currency": mv.currency,
                            "amount": mv.amount,
                        }
                        for mv in s.split_value
                    ],
                }
                for s in data.shared_with
            ],
        }

        result = await service.add_expense(request, input_dict)
        return _to_expense_payload(result)