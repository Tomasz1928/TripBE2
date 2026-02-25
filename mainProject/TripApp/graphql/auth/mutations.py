import strawberry
from strawberry.types import Info
from .types import AuthPayload, UserType
from ..utils import get_request
from . import service


def _to_auth_payload(result: dict) -> AuthPayload:
    user = result.get("user")
    return AuthPayload(
        success=result["success"],
        message=result["message"],
        user=UserType(id=user.id, username=user.username) if user else None,
    )


@strawberry.type
class AuthMutation:

    @strawberry.mutation
    async def register_user(self, info: Info, username: str, password: str) -> AuthPayload:
        result = await service.register_user(get_request(info), username, password)
        return _to_auth_payload(result)

    @strawberry.mutation
    async def login_user(self, info: Info, username: str, password: str) -> AuthPayload:
        result = await service.login_user(get_request(info), username, password)
        return _to_auth_payload(result)

    @strawberry.mutation
    async def logout_user(self, info: Info) -> AuthPayload:
        result = await service.logout_user(get_request(info))
        return _to_auth_payload(result)