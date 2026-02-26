import strawberry
from strawberry.types import Info
from .types import AddExpenseInput, UpdateExpenseInput
from ..shared_types import MutationPayload
from ..utils import get_request
from . import service


@strawberry.type
class ExpenseMutation:

    @strawberry.mutation
    async def add_expense(self, info: Info, data: AddExpenseInput) -> MutationPayload:
        result = await service.add_expense(get_request(info), _input_to_dict(data))
        return MutationPayload(success=result["success"], message=result["message"])

    @strawberry.mutation
    async def update_expense(self, info: Info, data: UpdateExpenseInput) -> MutationPayload:
        result = await service.update_expense(get_request(info), _input_to_dict(data))
        return MutationPayload(success=result["success"], message=result["message"])

    @strawberry.mutation
    async def delete_expense(self, info: Info, trip_id: int, expense_id: int) -> MutationPayload:
        result = await service.delete_expense(get_request(info), trip_id, expense_id)
        return MutationPayload(success=result["success"], message=result["message"])


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