"""
TripApp/graphql/receipt/types.py

Strawberry types for Receipt feature:
- ReceiptType: output type (query response)
- UploadReceiptPayload: mutation response
- HasReceiptType: lightweight flag returned in ExpenseDetailType
"""

import strawberry
from typing import Optional


@strawberry.type
class ReceiptType:
    """Full receipt data — returned by expenseReceipt query."""
    expense_id: int
    image_data: str
    uploaded_by_nickname: Optional[str] = None
    receipt_hash: Optional[str] = None
    created_at: float  # timestamp ms


@strawberry.type
class UploadReceiptPayload:
    """Response from uploadReceipt / deleteReceipt mutations."""
    success: bool
    message: str
