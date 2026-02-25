# graphql/mutations.py
import strawberry
from TripApp.graphql.authorization.mutations import AuthMutation


@strawberry.type
class Mutation(
    AuthMutation
):
    pass