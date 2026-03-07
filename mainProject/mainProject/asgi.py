import os
import sys
import asyncio
import logging
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mainProject.settings")
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.core.asgi import get_asgi_application
from django.urls import path
from strawberry.asgi import GraphQL
from TripApp.graphql.schema import schema

logger = logging.getLogger(__name__)

graphql_app = GraphQL(schema)


class SafeWebSocketApp:
    """
    Wrapper wokół Strawberry GraphQL ASGI app, który łapie
    StopAsyncIteration z osieroconych tasków subskrypcji.

    Problem: Kiedy klient zamyka WS (login/logout/resetAndRebuild),
    Strawberry próbuje zrobić asend()/anext() na zamkniętym async generatorze.
    To rzuca StopAsyncIteration, który nie jest łapany przez żaden handler
    i loguje się jako "Task exception was never retrieved".

    Ten wrapper:
    1. Instaluje globalny exception handler na czas życia połączenia WS
    2. Tłumi StopAsyncIteration (bezpieczne — to normalne przy disconneccie)
    3. Przepuszcza wszystkie inne wyjątki
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            # Zapamiętaj oryginalny handler
            loop = asyncio.get_event_loop()
            original_handler = loop.get_exception_handler()

            def ws_exception_handler(loop, context):
                exception = context.get("exception")
                if isinstance(exception, StopAsyncIteration):
                    # Normalne przy zamknięciu WS — tłumimy
                    logger.debug("Suppressed StopAsyncIteration from closed subscription")
                    return
                # Wszystko inne — przekaż do oryginalnego handlera
                if original_handler:
                    original_handler(loop, context)
                else:
                    loop.default_exception_handler(context)

            loop.set_exception_handler(ws_exception_handler)
            try:
                await self.app(scope, receive, send)
            finally:
                # Przywróć oryginalny handler
                loop.set_exception_handler(original_handler)
        else:
            await self.app(scope, receive, send)


application = ProtocolTypeRouter({
    # HTTP → Django's ASGI app handles everything through urls.py
    "http": get_asgi_application(),

    # WebSocket → Strawberry ASGI for subscriptions
    # SafeWebSocketApp tłumi StopAsyncIteration z zamkniętych subskrypcji
    "websocket": AuthMiddlewareStack(
        URLRouter([
            path("graphql/", SafeWebSocketApp(graphql_app)),
        ])
    ),
})