import asyncio

from src.config import load_config
from src.okx_client import OKXClient


async def test():
    config = load_config()
    okx_config = config.get_okx_config()

    async with OKXClient(okx_config) as client:
        balances = await client.get_account_balance()
        print(f"Balances count: {len(balances) if balances else 0}")
        if balances:
            print(f"First balance: {balances[0]}")
            for b in balances[:5]:  # Первые 5
                print(f"  {b.currency}: {b.total} (free: {b.free})")
        else:
            print("NO BALANCES FOUND!")


asyncio.run(test())
