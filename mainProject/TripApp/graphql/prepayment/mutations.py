import strawberry
from strawberry.types import Info
from ..shared_types import MutationPayload
from ..utils import get_request
from . import service


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
    ) -> MutationPayload:
        result = await service.add_prepayment(
            get_request(info), trip_id, participant_id, amount, currency, direction
        )
        return MutationPayload(success=result["success"], message=result["message"])