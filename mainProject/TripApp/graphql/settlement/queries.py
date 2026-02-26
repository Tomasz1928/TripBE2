import strawberry
from strawberry.types import Info
from asgiref.sync import sync_to_async
from TripApp.models import Trip, SettlementTripCurrency, SettlementOtherCurrency
from .types import (
    TripSettlementsType,
    SettlementTripCurrencyType,
    SettlementOtherCurrencyType,
)
from ..utils import get_request


@strawberry.type
class SettlementQuery:

    @strawberry.field
    async def trip_settlements(self, info: Info, trip_id: int) -> TripSettlementsType:
        trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)
        trip_currency = trip.default_currency.upper()

        trip_settlements = await sync_to_async(
            lambda: list(
                SettlementTripCurrency.objects.filter(trip=trip)
                .select_related("from_participant", "to_participant")
            )
        )()

        other_settlements = await sync_to_async(
            lambda: list(
                SettlementOtherCurrency.objects.filter(trip=trip)
                .select_related("from_participant", "to_participant")
            )
        )()

        return TripSettlementsType(
            trip_currency_settlements=[
                SettlementTripCurrencyType(
                    from_participant_id=s.from_participant_id,
                    from_nickname=s.from_participant.nickname,
                    to_participant_id=s.to_participant_id,
                    to_nickname=s.to_participant.nickname,
                    amount=float(s.amount),
                    currency=trip_currency,
                )
                for s in trip_settlements
            ],
            other_currency_settlements=[
                SettlementOtherCurrencyType(
                    from_participant_id=s.from_participant_id,
                    from_nickname=s.from_participant.nickname,
                    to_participant_id=s.to_participant_id,
                    to_nickname=s.to_participant.nickname,
                    amount=float(s.amount),
                    currency=s.currency,
                )
                for s in other_settlements
            ],
        )