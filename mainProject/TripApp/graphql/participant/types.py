import strawberry
from typing import Optional


@strawberry.type
class ParticipantType:
    participant_id: int
    nickname: str
    is_placeholder: bool
    access_code: Optional[str] = None
    user_id: Optional[int] = None


@strawberry.type
class ParticipantPayload:
    success: bool
    message: str
    participant: Optional[ParticipantType] = None