import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mainProject.settings")
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.core.asgi import get_asgi_application
from django.urls import path
from strawberry.asgi import GraphQL
from TripApp.graphql.schema import schema

graphql_app = GraphQL(schema)

application = ProtocolTypeRouter({
    # HTTP → Django's ASGI app handles everything through urls.py
    # This ensures real Django HttpRequest with sessions & middleware
    "http": get_asgi_application(),

    # WebSocket → Strawberry ASGI for subscriptions
    "websocket": AuthMiddlewareStack(
        URLRouter([
            path("graphql/", graphql_app),
        ])
    ),
})