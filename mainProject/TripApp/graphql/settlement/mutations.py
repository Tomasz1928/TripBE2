import strawberry
from typing import List
from strawberry.types import Info
from .types import (
    SettleByAmountPayload,
    SettleByCostsPayload,
    SettleByCostsItem,
)
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
    ) -> SettleByAmountPayload:
        result = await service.settle_by_amount(
            get_request(info),
            trip_id,
            from_user_id,
            to_user_id,
            amount,
            currency,
            is_main_currency,
        )
        return SettleByAmountPayload(
            success=result["success"],
            message=result["message"],
            settled_amount=result.get("settled_amount"),
            leftover_amount=result.get("leftover_amount"),
            prepayment_created=result.get("prepayment_created"),
        )

    @strawberry.mutation
    async def settle_by_costs(
        self,
        info: Info,
        trip_id: int,
        items: List[SettleByCostsItem],
    ) -> SettleByCostsPayload:
        items_dicts = [
            {
                "expense_id": item.expense_id,
                "payer_id": item.payer_id,
                "participant_id": item.participant_id,
            }
            for item in items
        ]
        result = await service.settle_by_costs(
            get_request(info), trip_id, items_dicts
        )
        return SettleByCostsPayload(
            success=result["success"],
            message=result["message"],
            settled_count=result.get("settled_count"),
        )