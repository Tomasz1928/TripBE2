import strawberry
from strawberry.tools import merge_types

from TripApp.middleware import RequireAuthenticationExtension


from .auth.queries import AuthQuery
from .auth.mutations import AuthMutation
from .trip.mutations import TripMutation
from .expense.mutations import ExpenseMutation
from .participant.mutations import ParticipantMutation
from .subscriptions import Subscription

Query = merge_types(
    "Query",
    (
        AuthQuery,
        # TripQuery,
        # ParticipantQuery,
        # ExpenseQuery,
        # SplitQuery,
        # SettlementQuery,
    ),
)

Mutation = merge_types(
    "Mutation",
    (
        AuthMutation,
        TripMutation,
        ExpenseMutation,
        ParticipantMutation,
        # SplitMutation,
        # SettlementMutation,
    ),
)

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    extensions=[RequireAuthenticationExtension],
)