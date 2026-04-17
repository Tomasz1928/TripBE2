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
        user=UserType(
            id=user.id,
            username=user.username,
            email=user.email or "",
        ) if user else None,
    )


@strawberry.type
class AuthMutation:

    @strawberry.mutation
    async def register_user(
        self, info: Info, username: str, password: str, email: str
    ) -> AuthPayload:
        result = await service.register_user(get_request(info), username, password, email)
        return _to_auth_payload(result)

    @strawberry.mutation
    async def login_user(self, info: Info, username: str, password: str) -> AuthPayload:
        result = await service.login_user(get_request(info), username, password)
        return _to_auth_payload(result)

    @strawberry.mutation
    async def logout_user(self, info: Info) -> AuthPayload:
        result = await service.logout_user(get_request(info))
        return _to_auth_payload(result)

    @strawberry.mutation
    async def reset_password(self, info: Info, username: str, email: str) -> AuthPayload:
        result = await service.reset_password(username, email)
        return _to_auth_payload(result)

    @strawberry.mutation
    async def change_email(self, info: Info, new_email: str) -> AuthPayload:
        result = await service.change_email(get_request(info), new_email)
        return _to_auth_payload(result)

    @strawberry.mutation
    async def change_password(
        self, info: Info, new_password: str, new_password_confirm: str
    ) -> AuthPayload:
        result = await service.change_password(
            get_request(info), new_password, new_password_confirm
        )
        return _to_auth_payload(result)