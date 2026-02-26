import strawberry
from strawberry.types import Info
from .types import (
    TripListType, TripListItemType,
    TripDetailType, SimpleMoneyValueType,
    CategoryType, ExpenseDetailType, ShareType,
    ParticipantDetailType, SettlementType, SettlementRelationType,
    PrepaymentDetailsType, PrepaymentHistoryType,
)
from ..utils import get_request
from . import service


def _to_money(d: dict) -> SimpleMoneyValueType:
    return SimpleMoneyValueType(
        is_main_currency=d["is_main_currency"],
        currency=d["currency"],
        amount=d["amount"],
    )


def _to_money_list(lst: list[dict]) -> list[SimpleMoneyValueType]:
    return [_to_money(d) for d in lst]


@strawberry.type
class TripQuery:

    @strawberry.field
    async def trip_list(self, info: Info) -> TripListType:
        trips = await service.get_trip_list(get_request(info))
        return TripListType(
            trips=[
                TripListItemType(
                    id=t["id"],
                    title=t["title"],
                    date_start=t["date_start"],
                    date_end=t["date_end"],
                    currency=t["currency"],
                    description=t["description"],
                    total_expenses=t["total_expenses"],
                    im_owner=t["im_owner"],
                )
                for t in trips
            ]
        )

    @strawberry.field
    async def trip_details(self, info: Info, trip_id: int) -> TripDetailType:
        data = await service.get_trip_details(get_request(info), trip_id)

        if data is None:
            raise PermissionError("You are not a participant in this trip.")

        # Categories
        categories = [
            CategoryType(category_id=c["category_id"], total_amount=c["total_amount"])
            for c in data["categories"]
        ]

        # Expenses
        expenses = [
            ExpenseDetailType(
                id=e["id"],
                name=e["name"],
                description=e["description"],
                total_expense=_to_money_list(e["total_expense"]),
                amount=e["amount"],
                currency=e["currency"],
                date=e["date"],
                category_id=e["category_id"],
                payer_id=e["payer_id"],
                payer_nickname=e["payer_nickname"],
                shared_with=[
                    ShareType(
                        participant_id=s["participant_id"],
                        participant_nickname=s["participant_nickname"],
                        split_value=_to_money_list(s["split_value"]),
                        is_settlement=s["is_settlement"],
                    )
                    for s in e["shared_with"]
                ],
            )
            for e in data["expenses"]
        ]

        # Participants
        participants = [
            ParticipantDetailType(
                id=p["id"],
                nickname=p["nickname"],
                total_expenses=_to_money_list(p["total_expenses"]),
                is_owner=p["is_owner"],
                is_placeholder=p["is_placeholder"],
                access_code=p["access_code"],
                is_active=p["is_active"],
            )
            for p in data["participants"]
        ]

        # Settlement
        settlement_data = data.get("settlement")
        settlement = None
        if settlement_data and settlement_data.get("relations"):
            settlement = SettlementType(
                relations=[
                    SettlementRelationType(
                        related_id=r["related_id"],
                        related_name=r["related_name"],
                        left_for_settled=_to_money_list(r["left_for_settled"]),
                        all_related_amount=_to_money_list(r["all_related_amount"]),
                        prepayment=PrepaymentDetailsType(
                            amount_left=_to_money_list(r["prepayment"]["amount_left"]),
                            history=[
                                PrepaymentHistoryType(
                                    date=h["date"],
                                    values=_to_money(h["values"]),
                                )
                                for h in r["prepayment"]["history"]
                            ],
                        ),
                    )
                    for r in settlement_data["relations"]
                ]
            )

        return TripDetailType(
            id=data["id"],
            title=data["title"],
            date_start=data["date_start"],
            date_end=data["date_end"],
            currency=data["currency"],
            description=data["description"],
            total_expenses=data["total_expenses"],
            categories=categories,
            owner_id=data["owner_id"],
            im_owner=data["im_owner"],
            my_cost=_to_money_list(data["my_cost"]),
            expenses=expenses,
            participants=participants,
            settlement=settlement,
        )