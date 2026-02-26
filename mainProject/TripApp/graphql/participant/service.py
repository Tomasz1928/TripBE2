import random
import string
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant
from TripApp.services.delta_builder import (
    build_participant_added_delta,
    build_participant_updated_delta,
    build_participant_removed_delta,
)
from TripApp.services.broadcast import broadcast_delta


def _generate_access_code() -> str:
    """Generate code in format XXXX-XXXX where X is [A-Z0-9]."""
    chars = string.ascii_uppercase + string.digits
    part1 = "".join(random.choices(chars, k=4))
    part2 = "".join(random.choices(chars, k=4))
    return f"{part1}-{part2}"


async def _generate_unique_access_code() -> str:
    """Generate access code that doesn't already exist in DB."""
    for _ in range(20):
        code = _generate_access_code()
        exists = await sync_to_async(
            Participant.objects.filter(access_code=code).exists
        )()
        if not exists:
            return code
    raise RuntimeError("Failed to generate unique access code after 20 attempts.")


async def _get_trip_and_verify_owner(request, trip_id: int) -> tuple:
    """Fetch trip and verify the requesting user is the trip owner."""
    user = await sync_to_async(lambda: request.user)()
    trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)

    owner_id = await sync_to_async(lambda: trip.trip_owner_id)()
    if owner_id != user.id:
        raise PermissionError("Only the trip owner can perform this action.")

    return trip, user


async def add_placeholder(request: HttpRequest, trip_id: int, nickname: str) -> dict:
    nickname = nickname.strip()

    if not nickname:
        return {"success": False, "message": "Nickname is required."}

    if len(nickname) > 25:
        return {"success": False, "message": "Nickname must be at most 25 characters."}

    trip, user = await _get_trip_and_verify_owner(request, trip_id)

    access_code = await _generate_unique_access_code()

    participant = await sync_to_async(Participant.objects.create)(
        trip=trip,
        user=None,
        nickname=nickname,
        is_placeholder=True,
        access_code=access_code,
    )

    # Broadcast delta
    delta = await build_participant_added_delta(trip, participant)
    await broadcast_delta(trip.trip_id, delta)

    return {"success": True, "message": "Placeholder added."}


async def detach_user(request: HttpRequest, trip_id: int, participant_id: int) -> dict:
    trip, user = await _get_trip_and_verify_owner(request, trip_id)

    participant = await sync_to_async(Participant.objects.get)(
        participant_id=participant_id, trip=trip
    )

    participant_user_id = await sync_to_async(lambda: participant.user_id)()
    if participant_user_id == user.id:
        return {"success": False, "message": "Cannot detach yourself from the trip."}

    if participant.is_placeholder:
        return {"success": False, "message": "Participant is already a placeholder."}

    new_code = await _generate_unique_access_code()

    participant.user = None
    participant.is_placeholder = True
    participant.access_code = new_code
    await sync_to_async(participant.save)()

    # Broadcast delta
    delta = await build_participant_updated_delta(trip, participant)
    await broadcast_delta(trip.trip_id, delta)

    return {"success": True, "message": "User detached. New access code generated."}


async def remove_placeholder(request: HttpRequest, trip_id: int, participant_id: int) -> dict:
    trip, user = await _get_trip_and_verify_owner(request, trip_id)

    participant = await sync_to_async(Participant.objects.get)(
        participant_id=participant_id, trip=trip
    )

    participant_user_id = await sync_to_async(lambda: participant.user_id)()
    if participant_user_id == user.id:
        return {"success": False, "message": "Cannot remove yourself from the trip."}

    if not participant.is_placeholder:
        return {"success": False, "message": "Cannot remove an active participant. Detach the user first."}

    removed_id = participant.participant_id
    await sync_to_async(participant.delete)()

    # Broadcast delta
    delta = await build_participant_removed_delta(trip, removed_id)
    await broadcast_delta(trip.trip_id, delta)

    return {"success": True, "message": "Placeholder removed."}


async def join_trip(request: HttpRequest, access_code: str) -> dict:
    access_code = access_code.strip().upper()

    if not access_code:
        return {"success": False, "message": "Access code is required."}

    user = await sync_to_async(lambda: request.user)()

    try:
        participant = await sync_to_async(Participant.objects.select_related("trip").get)(
            access_code=access_code, is_placeholder=True
        )
    except Participant.DoesNotExist:
        return {"success": False, "message": "Invalid or already used access code."}

    trip = await sync_to_async(lambda: participant.trip)()

    already_in = await sync_to_async(
        Participant.objects.filter(trip=trip, user=user).exists
    )()
    if already_in:
        return {"success": False, "message": "You are already a participant in this trip."}

    participant.user = user
    participant.is_placeholder = False
    participant.access_code = None
    await sync_to_async(participant.save)()

    # Broadcast delta
    delta = await build_participant_updated_delta(trip, participant)
    await broadcast_delta(trip.trip_id, delta)

    return {"success": True, "message": "Joined trip successfully."}