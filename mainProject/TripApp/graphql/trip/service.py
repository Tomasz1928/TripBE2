from datetime import datetime, timezone
from django.http import HttpRequest
from asgiref.sync import sync_to_async
from TripApp.models import Trip, Participant


async def create_trip(request: HttpRequest, title: str, date_start: int, date_end: int,
                      description: str, currency: str) -> dict:
    title = title.strip()
    currency = currency.strip().upper()
    description = description.strip()

    if not title:
        return {"success": False, "message": "Title is required."}

    if len(title) > 40:
        return {"success": False, "message": "Title must be at most 40 characters."}

    if not currency:
        return {"success": False, "message": "Currency is required."}

    if date_end <= date_start:
        return {"success": False, "message": "End date must be after start date."}

    start_date = datetime.fromtimestamp(date_start / 1000, tz=timezone.utc)
    end_date = datetime.fromtimestamp(date_end / 1000, tz=timezone.utc)

    user = await sync_to_async(lambda: request.user)()

    trip = await sync_to_async(Trip.objects.create)(
        trip_owner=user,
        title=title,
        description=description,
        start_date=start_date,
        end_date=end_date,
        default_currency=currency,
    )

    # Auto-create participant for trip owner (no access_code, not a placeholder)
    await sync_to_async(Participant.objects.create)(
        trip=trip,
        user=user,
        nickname=user.username,
        is_placeholder=False,
        access_code=None,
    )

    return {"success": True, "message": "Trip created successfully.", "trip": trip}