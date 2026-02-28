from decimal import Decimal


async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """
    Placeholder: returns 1:1 rate.
    TODO: fetch real rate from external API
    """
    if from_currency.upper() == to_currency.upper():
        return Decimal("1.000000")
    return Decimal("1.000000")