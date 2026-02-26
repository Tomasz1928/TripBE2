import strawberry
from strawberry.types import Info
from .types import PrepaymentPayload, PrepaymentType
from ..utils import get_request
from . import service


def _to_prepayment_payload(result: dict) -> PrepaymentPayload:
    prepayment = result.get("prepayment")
    from_p = result.get("from_participant")
    to_p = result.get("to_participant")

    if not prepayment:
        return PrepaymentPayload(
            success=result["success"],
            message=result["message"],
        )

    return PrepaymentPayload(
        success=result["success"],
        message=result["message"],
        prepayment=PrepaymentType(
            id=prepayment.id,
            from_participant_id=prepayment.from_participant_id,
            from_nickname=from_p.nickname,
            to_participant_id=prepayment.to_participant_id,
            to_nickname=to_p.nickname,
            amount=float(prepayment.amount),
            amount_left=float(prepayment.amount_left),
            currency=prepayment.currency,
            created_date=prepayment.created_date.isoformat(),
        ),
    )


@strawberry.type
class PrepaymentMutation:

    @strawberry.mutation
    async def add_prepayment(
        self,
        info: Info,
        trip_id: int,
        participant_id: int,
        amount: float,
        currency: str,
        direction: str,
    ) -> PrepaymentPayload:
        result = await service.add_prepayment(
            get_request(info), trip_id, participant_id, amount, currency, direction
        )
        return _to_prepayment_payload(result)