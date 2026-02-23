import strawberry
from .types import ItemType
from .queries import items

@strawberry.type
class Mutation:

    @strawberry.mutation
    def add_item(self, name: str) -> ItemType:
        item = ItemType(name=name)
        items.append(item)
        return item