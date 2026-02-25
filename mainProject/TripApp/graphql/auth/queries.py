import strawberry
from strawberry.types import Info
from .types import SessionInfo, UserType
from ..utils import get_request
from . import service


@strawberry.type
class AuthQuery:

    @strawberry.field
    async def session(self, info: Info) -> SessionInfo:
        result = await service.get_session(get_request(info))
        user = result["user"]
        return SessionInfo(
            is_authenticated=result["is_authenticated"],
            user=UserType(id=user.id, username=user.username) if user else None,
        )