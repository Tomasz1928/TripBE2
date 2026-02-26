"""
Broadcasting service — sends delta payloads through Django Channels layer
to all subscribers of a given trip.

Channel group naming: "trip_{trip_id}"
"""

import json
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def _get_group_name(trip_id: int) -> str:
    return f"trip_{trip_id}"


async def broadcast_delta(trip_id: int, delta_payload: dict) -> None:
    """
    Send a delta payload to all subscribers of a trip.

    The delta_payload is a plain dict (from delta_builder) that contains
    per_participant data. The subscription resolver will pick the right
    data for each subscriber.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    group_name = _get_group_name(trip_id)

    await channel_layer.group_send(
        group_name,
        {
            "type": "trip.delta",
            "payload": delta_payload,
        },
    )