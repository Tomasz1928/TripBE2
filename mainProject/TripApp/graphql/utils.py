from strawberry.types import Info
from django.http import HttpRequest


def get_request(info: Info) -> HttpRequest:
    """
    Extract Django HttpRequest from Strawberry context.

    - strawberry.django.views.GraphQLView  → info.context.request  (object with attrs)
    - strawberry.asgi.GraphQL (Daphne)     → info.context["request"]  (dict)
    """
    context = info.context

    if isinstance(context, dict):
        return context["request"]

    return context.request