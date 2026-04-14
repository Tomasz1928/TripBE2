from strawberry.extensions import SchemaExtension
from strawberry.types import Info
from asgiref.sync import sync_to_async
from TripApp.graphql.utils import get_request
import logging
import time

logger = logging.getLogger("TripApp.graphql")

PUBLIC_OPERATIONS = {
    "loginUser", "login_user",
    "registerUser", "register_user",
    "logoutUser", "logout_user",
    "session",
    "__schema", "__type",
}


class RequireAuthenticationExtension(SchemaExtension):

    async def resolve(self, _next, root, info: Info, *args, **kwargs):
        parent_name = info.parent_type.name if info.parent_type else None
        is_root = parent_name in ("Query", "Mutation", "Subscription")

        if is_root:
            field_name = info.field_name
            request = get_request(info)
            username = "anonymous"

            if field_name not in PUBLIC_OPERATIONS:
                is_auth = await sync_to_async(lambda: request.user.is_authenticated)()
                if not is_auth:
                    logger.warning("UNAUTH | operation=%s ip=%s", field_name, _get_ip(request))
                    raise PermissionError("Authentication required.")
                username = await sync_to_async(lambda: request.user.username)()
            else:
                try:
                    is_auth = await sync_to_async(lambda: request.user.is_authenticated)()
                    if is_auth:
                        username = await sync_to_async(lambda: request.user.username)()
                except Exception:
                    pass
            start = time.monotonic()
            try:
                result = _next(root, info, *args, **kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                elapsed = int((time.monotonic() - start) * 1000)
                logger.info("OK | user=%-20s op=%-30s %dms", username, field_name, elapsed)
                return result
            except PermissionError:
                raise
            except Exception as e:
                elapsed = int((time.monotonic() - start) * 1000)
                logger.error("ERR | user=%-20s op=%-30s %dms | %s: %s",
                             username, field_name, elapsed, type(e).__name__, e)
                raise

        result = _next(root, info, *args, **kwargs)
        if hasattr(result, "__await__"):
            return await result
        return result


def _get_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "?")