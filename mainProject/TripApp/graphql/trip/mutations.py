import strawberry
from typing import Optional
from strawberry.types import Info
from ..shared_types import MutationPayload
from ..utils import get_request
from . import service


@strawberry.type
class CreateTripPayload:
    success: bool
    message: str
    trip_id: Optional[int] = None


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
    ) -> CreateTripPayload:
        result = await service.create_trip(
            get_request(info), title, date_start, date_end, description, currency
        )
        trip = result.get("trip")
        return CreateTripPayload(
            success=result["success"],
            message=result["message"],
            trip_id=trip.trip_id if trip else None,
        )