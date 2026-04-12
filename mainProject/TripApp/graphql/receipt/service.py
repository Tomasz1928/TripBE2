import base64
from django.http import HttpRequest
from asgiref.sync import sync_to_async

from TripApp.models import Expense, Participant, Split, Receipt
from TripApp.services.actor_resolver import get_actor_participant_id
from TripApp.services.broadcast import broadcast_delta
from TripApp.services.delta_builder import build_receipt_changed_notification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_caller_participant(request: HttpRequest, expense: Expense):
    user = await sync_to_async(lambda: request.user)()
    trip = await sync_to_async(lambda: expense.trip)()
    return await sync_to_async(
        lambda: Participant.objects.filter(trip=trip, user=user).first()
    )()


async def _caller_is_involved(request: HttpRequest, expense: Expense) -> bool:
    participant = await _get_caller_participant(request, expense)
    if participant is None:
        return False

    pid = participant.participant_id
    payer_id = await sync_to_async(lambda: expense.payer_id)()
    if pid == payer_id:
        return True

    return await sync_to_async(
        lambda: Split.objects.filter(expense=expense, participant_id=pid).exists()
    )()


async def _caller_is_trip_participant(request, expense) -> bool:
    user = await sync_to_async(lambda: request.user)()
    trip = await sync_to_async(lambda: expense.trip)()
    return await sync_to_async(
        lambda: Participant.objects.filter(trip=trip, user=user).exists()
    )()

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_receipt(request, expense_id: int):
    try:
        expense = await sync_to_async(Expense.objects.get)(expense_id=expense_id)
    except Expense.DoesNotExist:
        return None

    # Podgląd dostępny dla każdego uczestnika tripa (nie tylko expense)
    if not await _caller_is_trip_participant(request, expense):
        return None

    receipt = await sync_to_async(
        lambda: Receipt.objects.filter(expense=expense).select_related('uploaded_by').first()
    )()

    if receipt is None:
        return None

    uploaded_by_nickname = await sync_to_async(
        lambda: receipt.uploaded_by.nickname if receipt.uploaded_by else None
    )()

    return {
        "expense_id": expense_id,
        "image_data": receipt.image_data,
        "receipt_hash": receipt.receipt_hash,
        "uploaded_by_nickname": uploaded_by_nickname,
        "created_at": receipt.created_at.timestamp() * 1000,
    }

# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

async def upload_receipt(
    request: HttpRequest,
    expense_id: int,
    image_data: str,
) -> dict:
    try:
        expense = await sync_to_async(
            lambda: Expense.objects.select_related('trip').get(expense_id=expense_id)
        )()
    except Expense.DoesNotExist:
        return {"success": False, "message": "Expense not found."}

    if not await _caller_is_involved(request, expense):
        return {"success": False, "message": "You are not involved in this expense."}

    # Validate base64
    try:
        decoded = base64.b64decode(image_data)
        if len(decoded) > 5 * 1024 * 1024:
            return {"success": False, "message": "Image too large (max 5 MB)."}
    except Exception:
        return {"success": False, "message": "Invalid image data."}

    participant = await _get_caller_participant(request, expense)

    # Upsert
    receipt, created = await sync_to_async(
        lambda: Receipt.objects.update_or_create(
            expense=expense,
            defaults={
                "image_data": image_data,
                "uploaded_by": participant,
            },
        )
    )()

    # update_or_create nie woła save() z naszym overridem przy update,
    # więc musimy ręcznie ustawić hash i zapisać
    await sync_to_async(receipt.save)()

    # Broadcast notification
    trip = await sync_to_async(lambda: expense.trip)()
    actor_id = await get_actor_participant_id(request, trip)
    notification = await build_receipt_changed_notification(trip, actor_id)
    await broadcast_delta(trip.trip_id, notification)

    action = "uploaded" if created else "replaced"
    return {"success": True, "message": f"Receipt {action} successfully."}


async def delete_receipt(
    request: HttpRequest,
    expense_id: int,
) -> dict:
    try:
        expense = await sync_to_async(
            lambda: Expense.objects.select_related('trip').get(expense_id=expense_id)
        )()
    except Expense.DoesNotExist:
        return {"success": False, "message": "Expense not found."}

    if not await _caller_is_involved(request, expense):
        return {"success": False, "message": "You are not involved in this expense."}

    deleted_count = await sync_to_async(
        lambda: Receipt.objects.filter(expense=expense).delete()
    )()

    if deleted_count[0] == 0:
        return {"success": False, "message": "No receipt to delete."}

    # Broadcast notification
    trip = await sync_to_async(lambda: expense.trip)()
    actor_id = await get_actor_participant_id(request, trip)
    notification = await build_receipt_changed_notification(trip, actor_id)
    await broadcast_delta(trip.trip_id, notification)

    return {"success": True, "message": "Receipt deleted successfully."}
