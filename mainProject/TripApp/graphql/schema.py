import strawberry
from strawberry.tools import merge_types

from TripApp.middleware import RequireAuthenticationExtension


from .auth.queries import AuthQuery
from .auth.mutations import AuthMutation
from .trip.queries import TripQuery
from .trip.mutations import TripMutation
from .expense.mutations import ExpenseMutation
from .participant.mutations import ParticipantMutation
from .prepayment.mutations import PrepaymentMutation
from .settlement.queries import SettlementQuery
from .settlement.mutations import SettlementMutation
from .subscriptions import Subscription
from .currency.queries import CurrencyQuery
from .receipt.queries import ReceiptQuery
from .receipt.mutations import ReceiptMutation

Query = merge_types(
    "Query",
    (
        AuthQuery,
        TripQuery,
        SettlementQuery,
        CurrencyQuery,
        ReceiptQuery,
    ),
)

Mutation = merge_types(
    "Mutation",
    (
        AuthMutation,
        TripMutation,
        ExpenseMutation,
        ParticipantMutation,
        PrepaymentMutation,
        SettlementMutation,
        ReceiptMutation,
    ),
)

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    extensions=[RequireAuthenticationExtension],
)