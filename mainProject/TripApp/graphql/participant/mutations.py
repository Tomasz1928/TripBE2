import strawberry
from strawberry.types import Info
from ..shared_types import MutationPayload
from ..utils import get_request
from . import service


@strawberry.type
class ParticipantMutation:

    @strawberry.mutation
    async def add_placeholder(self, info: Info, trip_id: int, nickname: str) -> MutationPayload:
        result = await service.add_placeholder(get_request(info), trip_id, nickname)
        return MutationPayload(success=result["success"], message=result["message"])

    @strawberry.mutation
    async def detach_user(self, info: Info, trip_id: int, participant_id: int) -> MutationPayload:
        result = await service.detach_user(get_request(info), trip_id, participant_id)
        return MutationPayload(success=result["success"], message=result["message"])

    @strawberry.mutation
    async def remove_placeholder(self, info: Info, trip_id: int, participant_id: int) -> MutationPayload:
        result = await service.remove_placeholder(get_request(info), trip_id, participant_id)
        return MutationPayload(success=result["success"], message=result["message"])

    @strawberry.mutation
    async def join_trip(self, info: Info, access_code: str) -> MutationPayload:
        result = await service.join_trip(get_request(info), access_code)
        return MutationPayload(success=result["success"], message=result["message"])