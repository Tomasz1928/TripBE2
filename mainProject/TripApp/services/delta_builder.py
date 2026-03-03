"""
Notification builder — builds lightweight notification payloads after mutations.

Each build_*_notification function returns a dict that can be sent
through the channel layer. The subscription resolver converts it
into a TripNotification type.
"""

from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant


async def _get_actor_nickname(trip: Trip, actor_participant_id: int) -> str:
    """Resolve actor's nickname from participant_id."""
    try:
        participant = await sync_to_async(
            Participant.objects.get
        )(participant_id=actor_participant_id, trip=trip)
        return participant.nickname
    except Participant.DoesNotExist:
        return "Unknown"


def _build_notification(
    trip: Trip,
    event_type: str,
    actor_nickname: str,
    actor_participant_id: int,
    target_participant_id: int | None = None,
) -> dict:
    """Build a lightweight notification payload."""
    payload = {
        "trip_id": trip.trip_id,
        "trip_name": trip.title,
        "event_type": event_type,
        "actor_nickname": actor_nickname,
        "actor_participant_id": actor_participant_id,
    }
    if target_participant_id is not None:
        payload["target_participant_id"] = target_participant_id
    return payload


# ---------------------------------------------------------------------------
# Public API — called from services after mutations
# ---------------------------------------------------------------------------

async def build_expense_added_notification(trip: Trip, actor_participant_id: int) -> dict:
    nickname = await _get_actor_nickname(trip, actor_participant_id)
    return _build_notification(trip, "EXPENSE_ADDED", nickname, actor_participant_id)


async def build_expense_updated_notification(trip: Trip, actor_participant_id: int) -> dict:
    nickname = await _get_actor_nickname(trip, actor_participant_id)
    return _build_notification(trip, "EXPENSE_UPDATED", nickname, actor_participant_id)


async def build_expense_deleted_notification(trip: Trip, actor_participant_id: int) -> dict:
    nickname = await _get_actor_nickname(trip, actor_participant_id)
    return _build_notification(trip, "EXPENSE_DELETED", nickname, actor_participant_id)


async def build_prepayment_notification(
    trip: Trip, actor_participant_id: int, target_participant_id: int | None = None
) -> dict:
    nickname = await _get_actor_nickname(trip, actor_participant_id)
    return _build_notification(
        trip, "PREPAYMENT_ADDED", nickname, actor_participant_id, target_participant_id
    )

async def build_settlement_changed_notification(
    trip: Trip, actor_participant_id: int, target_participant_id: int | None = None
) -> dict:
    nickname = await _get_actor_nickname(trip, actor_participant_id)
    return _build_notification(
        trip, "SETTLEMENT_CHANGED", nickname, actor_participant_id, target_participant_id
    )


async def build_participant_added_notification(trip: Trip, actor_participant_id: int) -> dict:
    nickname = await _get_actor_nickname(trip, actor_participant_id)
    return _build_notification(trip, "PARTICIPANT_ADDED", nickname, actor_participant_id)


async def build_participant_updated_notification(trip: Trip, actor_participant_id: int) -> dict:
    nickname = await _get_actor_nickname(trip, actor_participant_id)
    return _build_notification(trip, "PARTICIPANT_UPDATED", nickname, actor_participant_id)


async def build_participant_removed_notification(trip: Trip, actor_participant_id: int) -> dict:
    nickname = await _get_actor_nickname(trip, actor_participant_id)
    return _build_notification(trip, "PARTICIPANT_REMOVED", nickname, actor_participant_id)