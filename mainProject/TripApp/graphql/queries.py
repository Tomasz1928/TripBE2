import strawberry
from typing import List
from .types import ItemType

# tymczasowa baza
items = []

@strawberry.type
class Query:

    @strawberry.field
    def hello(self) -> str:
        return "Hello GraphQL 🚀"

    @strawberry.field
    def get_items(self) -> List[ItemType]:
        return items