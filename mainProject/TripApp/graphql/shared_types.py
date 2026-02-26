import strawberry


@strawberry.type
class MutationPayload:
    success: bool
    message: str