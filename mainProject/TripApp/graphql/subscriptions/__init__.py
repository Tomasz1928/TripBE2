import strawberry
import asyncio
from typing import AsyncGenerator
from channels.layers import get_channel_layer
from asgiref.sync import sync_to_async
from TripApp.models import Participant
from .types import TripDelta, TripEventType
from ..trip.types import (
    SimpleMoneyValueType, CategoryType, ExpenseDetailType,
    ShareType, ParticipantDetailType, SettlementType,
    SettlementRelationType, PrepaymentDetailsType, PrepaymentHistoryType,
)


def _to_money(d: dict) -> SimpleMoneyValueType:
    return SimpleMoneyValueType(
        is_main_currency=d["is_main_currency"],
        currency=d["currency"],
        amount=d["amount"],
    )


def _to_money_list(lst: list[dict]) -> list[SimpleMoneyValueType]:
    return [_to_money(d) for d in lst]


def _to_expense(e: dict) -> ExpenseDetailType:
    return ExpenseDetailType(
        id=e["id"],
        name=e["name"],
        description=e["description"],
        total_expense=_to_money_list(e["total_expense"]),
        amount=e["amount"],
        currency=e["currency"],
        date=e["date"],
        category_id=e["category_id"],
        payer_id=e["payer_id"],
        payer_nickname=e["payer_nickname"],
        shared_with=[
            ShareType(
                participant_id=s["participant_id"],
                participant_nickname=s["participant_nickname"],
                split_value=_to_money_list(s["split_value"]),
                is_settlement=s["is_settlement"],
            )
            for s in e["shared_with"]
        ],
    )


def _to_participant(p: dict) -> ParticipantDetailType:
    return ParticipantDetailType(
        id=p["id"],
        nickname=p["nickname"],
        total_expenses=_to_money_list(p["total_expenses"]),
        is_owner=p["is_owner"],
        is_placeholder=p["is_placeholder"],
        access_code=p["access_code"],
        is_active=p["is_active"],
    )


def _to_settlement(data: dict | None) -> SettlementType | None:
    if not data or not data.get("relations"):
        return None

    return SettlementType(
        relations=[
            SettlementRelationType(
                related_id=r["related_id"],
                related_name=r["related_name"],
                left_for_settled=_to_money_list(r["left_for_settled"]),
                all_related_amount=_to_money_list(r["all_related_amount"]),
                prepayment=PrepaymentDetailsType(
                    amount_left=_to_money_list(r["prepayment"]["amount_left"]),
                    history=[
                        PrepaymentHistoryType(
                            date=h["date"],
                            values=_to_money(h["values"]),
                        )
                        for h in r["prepayment"]["history"]
                    ],
                ),
            )
            for r in data["relations"]
        ],
    )


def _payload_to_delta(payload: dict, participant_id: int) -> TripDelta:
    """Convert raw channel payload to a typed TripDelta for a specific subscriber."""

    per_p = payload.get("per_participant", {}).get(participant_id, {})

    # Event type
    event_type = TripEventType(payload["event_type"])

    # Expenses
    expenses = None
    if payload.get("expenses"):
        expenses = [_to_expense(e) for e in payload["expenses"]]

    # Participants
    participants = None
    if payload.get("participants"):
        participants = [_to_participant(p) for p in payload["participants"]]

    # Categories
    categories = None
    if payload.get("categories"):
        categories = [
            CategoryType(category_id=c["category_id"], total_amount=c["total_amount"])
            for c in payload["categories"]
        ]

    # Settlement (per-user perspective)
    settlement = _to_settlement(per_p.get("settlement"))

    # My cost (per-user)
    my_cost = None
    if per_p.get("my_cost"):
        my_cost = _to_money_list(per_p["my_cost"])

    return TripDelta(
        trip_id=payload["trip_id"],
        event_type=event_type,
        expenses=expenses,
        participants=participants,
        categories=categories,
        settlement=settlement,
        removed_expense_ids=payload.get("removed_expense_ids"),
        removed_participant_ids=payload.get("removed_participant_ids"),
        total_expenses=payload.get("total_expenses"),
        my_cost=my_cost,
    )


@strawberry.type
class Subscription:

    @strawberry.subscription
    async def trip_delta(self, info: strawberry.types.Info, trip_id: int) -> AsyncGenerator[TripDelta, None]:
        """
        Subscribe to real-time deltas for a specific trip.

        The subscriber must be a participant in the trip.
        Each delta is personalized with the subscriber's settlement perspective.
        """
        channel_layer = get_channel_layer()
        if channel_layer is None:
            raise RuntimeError("Channel layer not configured.")

        # Auth: resolve subscriber's participant_id
        # In WebSocket context, info.context is a dict
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

        try:
            while True:
                # Wait for messages from the group
                message = await channel_layer.receive(channel_name)

                if message["type"] == "trip.delta":
                    payload = message["payload"]
                    delta = _payload_to_delta(payload, my_participant_id)
                    yield delta

        except asyncio.CancelledError:
            pass
        finally:
            await channel_layer.group_discard(group_name, channel_name)