from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from strawberry.django.views import AsyncGraphQLView
from TripApp.graphql.schema import schema
from django.http import HttpResponse

def ping(request):
    return HttpResponse("pong", content_type="text/plain")

urlpatterns = [
    path("graphql/", csrf_exempt(AsyncGraphQLView.as_view(schema=schema))),
    path("ping/", ping, name="ping")
]