import strawberry
from typing import List
from strawberry.types import Info
from .types import SettleByCostsItem
from ..shared_types import MutationPayload
from ..utils import get_request
from . import service


@strawberry.type
class SettlementMutation:

    @strawberry.mutation
    async def settle_by_amount(
        self,
        info: Info,
        trip_id: int,
        from_user_id: int,
        to_user_id: int,
        amount: float,
        currency: str,
        is_main_currency: bool,
    ) -> MutationPayload:
        result = await service.settle_by_amount(
            get_request(info),
            trip_id, from_user_id, to_user_id,
            amount, currency, is_main_currency,
        )
        return MutationPayload(success=result["success"], message=result["message"])

    @strawberry.mutation
    async def settle_by_costs(
        self,
        info: Info,
        trip_id: int,
        items: List[SettleByCostsItem],
    ) -> MutationPayload:
        items_dicts = [
            {
                "expense_id": item.expense_id,
                "participant_id": item.participant_id,
            }
            for item in items
        ]
        result = await service.settle_by_costs(
            get_request(info), trip_id, items_dicts
        )
        return MutationPayload(success=result["success"], message=result["message"])