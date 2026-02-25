from strawberry.extensions import SchemaExtension
from strawberry.types import Info
from TripApp.graphql.utils import get_request


PUBLIC_OPERATIONS = {
    "loginUser",
    "login_user",
    "registerUser",
    "register_user",
    "logoutUser",
    "logout_user",
    "session",
    "__schema",
    "__type",
}


class RequireAuthenticationExtension(SchemaExtension):
    """
    Strawberry schema extension that blocks unauthenticated access
    to all queries/mutations except those listed in PUBLIC_OPERATIONS.
    """

    def resolve(self, _next, root, info: Info, *args, **kwargs):
        parent_name = info.parent_type.name if info.parent_type else None
        is_root = parent_name in ("Query", "Mutation", "Subscription")

        if is_root:
            field_name = info.field_name

            if field_name not in PUBLIC_OPERATIONS:
                request = get_request(info)
                if not request.user.is_authenticated:
                    raise PermissionError("Authentication required.")

        return _next(root, info, *args, **kwargs)