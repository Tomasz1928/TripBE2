import strawberry
from strawberry.types import Info
from .types import TripPayload, TripType
from ..utils import get_request
from . import service


def _to_trip_payload(result: dict) -> TripPayload:
    trip = result.get("trip")
    return TripPayload(
        success=result["success"],
        message=result["message"],
        trip=TripType(
            trip_id=trip.trip_id,
            title=trip.title,
            description=trip.description,
            start_date=trip.start_date.isoformat(),
            end_date=trip.end_date.isoformat(),
            default_currency=trip.default_currency,
            owner_id=trip.trip_owner_id,
        ) if trip else None,
    )


@strawberry.type
class TripMutation:

    @strawberry.mutation
    async def create_trip(
        self,
        info: Info,
        title: str,
        date_start: float,
        date_end: float,
        description: str = "",
        currency: str = "PLN",
    ) -> TripPayload:
        result = await service.create_trip(
            get_request(info), title, date_start, date_end, description, currency
        )
        return _to_trip_payload(result)