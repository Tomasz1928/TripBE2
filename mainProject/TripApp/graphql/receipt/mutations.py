"""
TripApp/graphql/receipt/mutations.py

GraphQL mutations for receipts:
- uploadReceipt(expenseId, imageData): upload or replace receipt
- deleteReceipt(expenseId): delete receipt
"""

import strawberry
from strawberry.types import Info

from .types import UploadReceiptPayload
from .service import upload_receipt, delete_receipt
from ..utils import get_request


@strawberry.type
class ReceiptMutation:

    @strawberry.mutation
    async def upload_receipt(
        self,
        info: Info,
        expense_id: int,
        image_data: str,
    ) -> UploadReceiptPayload:
        """
        Upload or replace a receipt image for an expense.

        Args:
            expense_id: ID of the expense
            image_data: base64-encoded JPEG string (compressed on client)

        Returns:
            UploadReceiptPayload with success status
        """
        result = await upload_receipt(
            get_request(info),
            expense_id,
            image_data,
        )
        return UploadReceiptPayload(
            success=result["success"],
            message=result["message"],
        )

    @strawberry.mutation
    async def delete_receipt(
        self,
        info: Info,
        expense_id: int,
    ) -> UploadReceiptPayload:
        """
        Delete receipt image for an expense.

        Args:
            expense_id: ID of the expense

        Returns:
            UploadReceiptPayload with success status
        """
        result = await delete_receipt(
            get_request(info),
            expense_id,
        )
        return UploadReceiptPayload(
            success=result["success"],
            message=result["message"],
        )
