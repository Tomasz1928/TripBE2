"""
TripApp/graphql/receipt/queries.py

GraphQL queries for receipts:
- expenseReceipt(expenseId): fetch full receipt image (lazy load)
"""

import strawberry
from typing import Optional
from strawberry.types import Info

from .types import ReceiptType
from .service import get_receipt
from ..utils import get_request


@strawberry.type
class ReceiptQuery:

    @strawberry.field
    async def expense_receipt(
        self, info: Info, expense_id: int
    ) -> Optional[ReceiptType]:
        """
        Fetch receipt image for a specific expense.
        Returns null if no receipt exists or caller has no access.

        This is a SEPARATE query from tripDetails — called on-demand
        when user taps "Zobacz rachunek" in the expense detail modal.
        """
        result = await get_receipt(get_request(info), expense_id)

        if result is None:
            return None

        return ReceiptType(
            expense_id=result["expense_id"],
            image_data=result["image_data"],
            uploaded_by_nickname=result["uploaded_by_nickname"],
            created_at=result["created_at"],
            receipt_hash=result["receipt_hash"],
        )
