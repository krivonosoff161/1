"""Simple OCO test without emojis"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv
from loguru import logger

from src.config import APIConfig
from src.models import OrderSide, OrderType
from src.okx_client import OKXClient

logger.remove()
logger.add(sys.stdout, level="DEBUG")


async def test():
    load_dotenv()

    config = APIConfig(
        api_key=os.getenv("OKX_API_KEY"),
        api_secret=os.getenv("OKX_API_SECRET"),
        passphrase=os.getenv("OKX_PASSPHRASE"),
        sandbox=True,
    )

    client = OKXClient(config)

    try:
        await client.connect()
        print("\n[1] Connected\n")

        # Get balance before
        print("[2] Getting USDT balance...")
        usdt_before = await client.get_balance("USDT")
        print(f"    USDT: ${usdt_before:.2f}\n")

        print("[3] Getting ETH balance...")
        eth_before = await client.get_balance("ETH")
        print(f"    ETH: {eth_before:.8f}\n")

        # Place BUY order
        print("[4] Placing BUY order for $20 USDT...")
        order = await client.place_order(
            symbol="ETH-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=20.0,
        )
        print(f"    Order ID: {order.id}\n")

        # Wait and check balance
        await asyncio.sleep(1)

        print("[5] Getting ETH balance after BUY...")
        eth_after = await client.get_balance("ETH")
        print(f"    ETH after: {eth_after:.8f}")
        print(f"    Bought: {eth_after - eth_before:.8f}\n")

        # Get current price
        print("[6] Getting ticker...")
        ticker = await client.get_ticker("ETH-USDT")
        current_price = float(ticker.get("last", 0))
        print(f"    Price: ${current_price:.2f}\n")

        # Calculate TP/SL
        tp_price = current_price * 0.999
        sl_price = current_price * 1.002
        actual_eth = eth_after - eth_before

        print(f"[7] Placing OCO order...")
        print(f"    Size: {actual_eth:.8f} ETH")
        print(f"    TP: ${tp_price:.2f}")
        print(f"    SL: ${sl_price:.2f}")
        print(f"    Endpoint: POST /trade/order-algo")
        print()

        oco_id = await client.place_oco_order(
            symbol="ETH-USDT",
            side=OrderSide.SELL,
            quantity=actual_eth,
            tp_trigger_price=tp_price,
            sl_trigger_price=sl_price,
        )
        print(f"    OCO ID: {oco_id}\n")

        # CRITICAL: Check balance RIGHT AFTER OCO
        print("[8] CRITICAL: Getting balance RIGHT AFTER OCO...")
        print("    This is where Invalid Sign usually appears!")
        print()

        try:
            eth_after_oco = await client.get_balance("ETH")
            print(f"    SUCCESS: ETH = {eth_after_oco:.8f}")
        except Exception as e:
            print(f"    ERROR: {e}")
            print(f"    >>> FOUND IT! Invalid Sign appears HERE!")
            raise

        print("\n[9] Test completed!")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test())
