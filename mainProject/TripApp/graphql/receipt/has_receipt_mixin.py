from asgiref.sync import sync_to_async
from TripApp.models import Receipt


async def batch_receipt_hashes(expense_ids: list[int]) -> dict[int, str | None]:
    """
    Batch load receipt hashes for expenses.
    Returns: {expense_id: "md5hash"} for expenses with receipts,
             expense_id not in dict = no receipt.
    """
    if not expense_ids:
        return {}

    receipts = await sync_to_async(
        lambda: dict(
            Receipt.objects.filter(expense_id__in=expense_ids)
            .values_list('expense_id', 'receipt_hash')
        )
    )()

    return receipts