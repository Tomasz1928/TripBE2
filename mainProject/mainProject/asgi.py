import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from strawberry.asgi import GraphQL



os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mainProject.settings")
django.setup()

from TripApp.graphql.schema import schema

graphql_app = GraphQL(schema)

application = ProtocolTypeRouter({
    "http": URLRouter([
        path("graphql/", graphql_app),
    ]),
    "websocket": URLRouter([
        path("graphql/", graphql_app),
    ]),
})