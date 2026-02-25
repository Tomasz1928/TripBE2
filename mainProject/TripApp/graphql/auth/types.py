import strawberry
from typing import Optional


@strawberry.type
class UserType:
    id: int
    username: str


@strawberry.type
class AuthPayload:
    success: bool
    message: str
    user: Optional[UserType] = None


@strawberry.type
class SessionInfo:
    is_authenticated: bool
    user: Optional[UserType] = None