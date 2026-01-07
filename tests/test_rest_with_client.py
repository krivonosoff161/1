#!/usr/bin/env python3
"""
Тест REST API с параметрами как в реальном боте
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from clients.futures_client import OKXFuturesClient
from config import BotConfig


async def main():
    print("=" * 60)
    print("REST API TEST WITH REAL CLIENT")
    print("=" * 60)

    try:
        # 1. Load config
        print("\n[1] Loading config...")
        config = BotConfig.load_from_file("config/config_futures.yaml")
        api_config = config.get_okx_config()
        print(f"    API Key: {api_config.api_key[:10]}...")
        print(f"    Passphrase: {api_config.passphrase[:5]}...")

        # 2. Create client
        print("\n[2] Creating OKXFuturesClient...")
        client = OKXFuturesClient(
            api_key=api_config.api_key,
            secret_key=api_config.api_secret,
            passphrase=api_config.passphrase,
        )
        print(f"    Base URL: {client.base_url}")
        print(f"    API Key set: {bool(client.api_key)}")

        # 3. Test system status (public, no auth needed)
        print("\n[3] Testing public endpoint: /system/status")
        try:
            status = await client.get_system_status()
            print(f"    SUCCESS: {status}")
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {str(e)[:80]}")

        # 4. Test leverage info (public, but symbol-specific)
        print("\n[4] Testing public endpoint: leverage info for ETH-USDT")
        try:
            info = await client.get_instrument_leverage_info("ETH-USDT")
            print(f"    SUCCESS: max_leverage={info.get('max_leverage')}x")
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {str(e)[:80]}")

        # 5. Test market ticker (public)
        print("\n[5] Testing public endpoint: market ticker for BTC-USDT")
        try:
            ticker = await client.get_ticker("BTC-USDT")
            print(f"    SUCCESS: price={ticker.get('last')}")
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {str(e)[:80]}")

        # 6. Test account balance (private, needs auth)
        print("\n[6] Testing private endpoint: account balance")
        try:
            balance = await client.get_balance()
            print(f"    SUCCESS: {balance}")
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {str(e)[:80]}")

        # 7. Test positions (private, needs auth)
        print("\n[7] Testing private endpoint: positions")
        try:
            positions = await client.get_positions()
            print(f"    SUCCESS: {len(positions)} positions")
        except Exception as e:
            print(f"    FAILED: {type(e).__name__}: {str(e)[:80]}")

        await client.close()
        print("\n" + "=" * 60)
        print("TESTS COMPLETED")
        print("=" * 60)

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
