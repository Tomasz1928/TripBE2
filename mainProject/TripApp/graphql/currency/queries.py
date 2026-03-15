import strawberry
from typing import List
from .constants import AVAILABLE_CURRENCIES


@strawberry.type
class CurrencyQuery:

    @strawberry.field
    async def available_currencies(self) -> List[str]:
        return AVAILABLE_CURRENCIES