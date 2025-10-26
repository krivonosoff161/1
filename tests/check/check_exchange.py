import sys

sys.path.append("src")
import asyncio
import json

from src.config import load_config
from src.okx_client import OKXClient


async def get_exchange_data():
    print("🔍 ПОДКЛЮЧЕНИЕ К OKX...")
    try:
        config = load_config()
        client = OKXClient(config.api["okx"])
        await client.connect()
        print("✅ Подключение успешно")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return

    print("\n💰 ПРОВЕРКА БАЛАНСА...")
    try:
        # Получаем баланс для всех валют
        result = await client._make_request("GET", "/account/balance")
        print("📊 Полный ответ от биржи:")
        print(json.dumps(result, indent=2))

        # Парсим баланс
        if "data" in result and result["data"]:
            for account in result["data"]:
                print(f'\n📈 Аккаунт: {account.get("acctLv", "unknown")}')
                print(f"💰 Детали баланса:")
                for detail in account.get("details", []):
                    currency = detail.get("ccy", "unknown")
                    available = float(detail.get("availBal", 0))
                    frozen = float(detail.get("frozenBal", 0))
                    total = available + frozen
                    if total > 0:
                        print(
                            f"  {currency}: {total:.6f} (доступно: {available:.6f}, заморожено: {frozen:.6f})"
                        )
    except Exception as e:
        print(f"❌ Ошибка получения баланса: {e}")

    print("\n📋 ПРОВЕРКА ОРДЕРОВ...")
    try:
        orders = await client.get_open_orders()
        print(f"📈 Открытых ордеров: {len(orders)}")
        if orders:
            for order in orders:
                print(
                    f"  {order.symbol} {order.side} {order.size} @ {order.price} - {order.status}"
                )
    except Exception as e:
        print(f"❌ Ошибка получения ордеров: {e}")

    print("\n🎯 ПРОВЕРКА ПОЗИЦИЙ...")
    try:
        positions = await client.get_positions()
        print(f"📊 Открытых позиций: {len(positions)}")
        if positions:
            for pos in positions:
                print(f"  {pos.symbol} {pos.side} {pos.size} PnL: {pos.unrealized_pnl}")
    except Exception as e:
        print(f"❌ Ошибка получения позиций: {e}")

    print("\n📊 ИСТОРИЯ ОРДЕРОВ...")
    try:
        # Получаем историю ордеров
        history_result = await client._make_request(
            "GET", "/trade/orders-history?instType=SPOT&limit=20"
        )
        print(f"📋 История ордеров:")
        print(json.dumps(history_result, indent=2))
    except Exception as e:
        print(f"❌ Ошибка получения истории: {e}")

    await client.disconnect()


# Запускаем
if __name__ == "__main__":
    asyncio.run(get_exchange_data())
