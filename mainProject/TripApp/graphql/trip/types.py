import strawberry
from typing import Optional


@strawberry.type
class TripType:
    trip_id: int
    title: str
    description: str
    start_date: str
    end_date: str
    default_currency: str
    owner_id: int


@strawberry.type
class TripPayload:
    success: bool
    message: str
    trip: Optional[TripType] = None


