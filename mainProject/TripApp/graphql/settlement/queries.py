import strawberry
from strawberry.types import Info
from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant, ParticipantRelation
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
        """
        Return settlement summaries from ParticipantRelation.
        Splits left_for_settled entries into trip currency and other currency lists
        for backward compatibility with the existing GraphQL schema.
        """
        trip = await sync_to_async(Trip.objects.get)(trip_id=trip_id)
        trip_currency = trip.default_currency.upper()

        relations = await sync_to_async(
            lambda: list(
                ParticipantRelation.objects.filter(trip=trip)
                .select_related("participant_a", "participant_b")
            )
        )()

        trip_currency_settlements = []
        other_currency_settlements = []

        for rel in relations:
            a = rel.participant_a
            b = rel.participant_b

            for entry in rel.left_for_settled:
                amount = entry.get("amount", 0)
                if amount == 0:
                    continue

                # Determine direction: positive = B owes A
                if amount > 0:
                    from_p, to_p = b, a
                else:
                    from_p, to_p = a, b
                    amount = -amount

                currency = entry.get("currency", trip_currency)
                is_main = entry.get("is_main_currency", False)

                if is_main:
                    trip_currency_settlements.append(
                        SettlementTripCurrencyType(
                            from_participant_id=from_p.participant_id,
                            from_nickname=from_p.nickname,
                            to_participant_id=to_p.participant_id,
                            to_nickname=to_p.nickname,
                            amount=amount,
                            currency=trip_currency,
                        )
                    )
                else:
                    other_currency_settlements.append(
                        SettlementOtherCurrencyType(
                            from_participant_id=from_p.participant_id,
                            from_nickname=from_p.nickname,
                            to_participant_id=to_p.participant_id,
                            to_nickname=to_p.nickname,
                            amount=amount,
                            currency=currency,
                        )
                    )

        return TripSettlementsType(
            trip_currency_settlements=trip_currency_settlements,
            other_currency_settlements=other_currency_settlements,
        )