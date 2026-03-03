"""
Resolve the actor's participant_id from request and trip.
"""

from asgiref.sync import sync_to_async
from django.http import HttpRequest
from TripApp.models import Participant, Trip


async def get_actor_participant_id(request: HttpRequest, trip: Trip) -> int:
    """
    Get the participant_id of the currently authenticated user for a given trip.
    Returns -1 if not found (shouldn't happen if auth middleware works).
    """
    user = await sync_to_async(lambda: request.user)()
    participant = await sync_to_async(
        lambda: Participant.objects.filter(trip=trip, user=user).first()
    )()
    return participant.participant_id if participant else -1