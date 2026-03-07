import strawberry
import asyncio
import logging
from typing import AsyncGenerator
from channels.layers import get_channel_layer
from asgiref.sync import sync_to_async
from TripApp.models import Participant
from .types import TripNotification, TripEventType

logger = logging.getLogger(__name__)

@strawberry.type
class Subscription:

    @strawberry.subscription
    async def trip_updates(
        self, info: strawberry.types.Info, trip_id: int
    ) -> AsyncGenerator[TripNotification, None]:
        """
        Subscribe to real-time notifications for a specific trip.

        The subscriber must be a participant in the trip.
        Notifications from the subscriber themselves are filtered out.
        """
        channel_layer = get_channel_layer()
        if channel_layer is None:
            raise RuntimeError("Channel layer not configured.")

        # Auth
        context = info.context
        if isinstance(context, dict):
            request = context.get("request")
        else:
            request = getattr(context, "request", None)

        if request is None:
            raise PermissionError("Authentication required.")

        user = await sync_to_async(lambda: request.user)()
        is_auth = await sync_to_async(lambda: user.is_authenticated)()
        if not is_auth:
            raise PermissionError("Authentication required.")

        participant = await sync_to_async(
            lambda: Participant.objects.filter(trip_id=trip_id, user=user).first()
        )()
        if not participant:
            raise PermissionError("You are not a participant in this trip.")

        my_participant_id = participant.participant_id

        # Create a unique channel for this subscriber
        channel_name = await channel_layer.new_channel()
        group_name = f"trip_{trip_id}"

        await channel_layer.group_add(group_name, channel_name)
        logger.info(f"Subscription started: trip={trip_id}, participant={my_participant_id}, channel={channel_name}")

        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        channel_layer.receive(channel_name),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    continue

                if message["type"] == "trip.delta":
                    payload = message["payload"]

                    # Skip notifications from the actor themselves
                    if payload.get("actor_participant_id") == my_participant_id:
                        continue

                    # If targeted — only deliver to target participant
                    target_id = payload.get("target_participant_id")
                    if target_id is not None and target_id != my_participant_id:
                        continue

                    notification = TripNotification(
                        trip_id=payload["trip_id"],
                        trip_name=payload["trip_name"],
                        event_type=TripEventType(payload["event_type"]),
                        actor_nickname=payload["actor_nickname"],
                        actor_participant_id=payload["actor_participant_id"],
                    )
                    yield notification

        except (asyncio.CancelledError, GeneratorExit):
            logger.info(f"Subscription cancelled: trip={trip_id}, participant={my_participant_id}")
        except Exception as e:
            logger.warning(f"Subscription error: trip={trip_id}, {type(e).__name__}: {e}")
        finally:
            await channel_layer.group_discard(group_name, channel_name)
            logger.info(f"Subscription cleaned up: trip={trip_id}, channel={channel_name}")