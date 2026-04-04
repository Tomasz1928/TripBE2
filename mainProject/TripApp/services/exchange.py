from decimal import Decimal, ROUND_HALF_UP
import requests

async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    url = f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{from_currency.lower()}.json"

    base_rates = {}

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        base_rates = next((v for k, v in data.items() if k != "date"), {})

    except Exception as e:
        print(f"Error fetching rates for {from_currency}: {e}")

    rate = base_rates.get(to_currency.lower())

    if rate is None:
        return Decimal('1.00')

    return Decimal(str(rate)).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)


