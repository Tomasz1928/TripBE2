import strawberry
from strawberry.types import Info
from asgiref.sync import sync_to_async

from TripApp.services.authorization.login import login_user, logout_user
from TripApp.services.authorization.registration import register_user


@strawberry.type
class AuthMutation:

    @strawberry.mutation
    async def login_user(self, info: Info, username: str, password: str) -> bool:
        scope = info.context
        request = scope.get("request")
        return await sync_to_async(login_user)(request, username, password)

    @strawberry.mutation
    async def logout_user(self, info: Info) -> bool:
        request = info.context
        return await sync_to_async(logout_user)(request)

    @strawberry.mutation
    async def registry_user(self, username: str, password: str) -> bool:
        user = await sync_to_async(register_user)(username, password)
        return user is not None