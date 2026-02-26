import strawberry
from strawberry.types import Info
from .types import ParticipantPayload, ParticipantType
from ..utils import get_request
from . import service


def _to_participant_payload(result: dict) -> ParticipantPayload:
    p = result.get("participant")
    return ParticipantPayload(
        success=result["success"],
        message=result["message"],
        participant=ParticipantType(
            participant_id=p.participant_id,
            nickname=p.nickname,
            is_placeholder=p.is_placeholder,
            access_code=p.access_code,
            user_id=p.user_id,
        ) if p else None,
    )


@strawberry.type
class ParticipantMutation:

    @strawberry.mutation
    async def add_placeholder(self, info: Info, trip_id: int, nickname: str) -> ParticipantPayload:
        result = await service.add_placeholder(get_request(info), trip_id, nickname)
        return _to_participant_payload(result)

    @strawberry.mutation
    async def detach_user(self, info: Info, trip_id: int, participant_id: int) -> ParticipantPayload:
        result = await service.detach_user(get_request(info), trip_id, participant_id)
        return _to_participant_payload(result)

    @strawberry.mutation
    async def remove_placeholder(self, info: Info, trip_id: int, participant_id: int) -> ParticipantPayload:
        result = await service.remove_placeholder(get_request(info), trip_id, participant_id)
        return _to_participant_payload(result)

    @strawberry.mutation
    async def join_trip(self, info: Info, access_code: str) -> ParticipantPayload:
        result = await service.join_trip(get_request(info), access_code)
        return _to_participant_payload(result)