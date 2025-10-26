"""
ТЕСТ ИСПРАВЛЕНИЯ OCO ОРДЕРОВ
Проверяем что теперь API видит OCO ордера
"""

import asyncio
import sys

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def test_oco_orders_fix():
    """Тест исправления OCO ордеров"""
    print("🔧 ТЕСТ ИСПРАВЛЕНИЯ OCO ОРДЕРОВ")
    print("=" * 60)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ПРОВЕРКА OCO ОРДЕРОВ
        print(f"\n🤖 ПРОВЕРКА OCO ОРДЕРОВ:")
        print("-" * 50)

        try:
            # Проверяем OCO ордера
            oco_orders = await bot.client.get_algo_orders(algo_type="oco")
            print(f"📊 OCO ордеров: {len(oco_orders)}")

            for i, order in enumerate(oco_orders, 1):
                print(f"   {i}. Algo ID: {order.get('algoId')}")
                print(f"      Symbol: {order.get('instId')}")
                print(f"      Type: {order.get('ordType')}")
                print(f"      Side: {order.get('side')}")
                print(f"      Size: {order.get('sz')}")
                print(f"      TP: {order.get('tpTriggerPx')}")
                print(f"      SL: {order.get('slTriggerPx')}")
                print(f"      State: {order.get('state')}")
                print()

        except Exception as e:
            print(f"❌ Ошибка получения OCO ордеров: {e}")

        # 2. ПРОВЕРКА ВСЕХ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ
        print(f"\n🤖 ВСЕ АЛГОРИТМИЧЕСКИЕ ОРДЕРА:")
        print("-" * 50)

        try:
            # Проверяем все типы
            all_algo_orders = await bot.client.get_algo_orders()
            print(f"📊 Всего алгоритмических ордеров: {len(all_algo_orders)}")

            for i, order in enumerate(all_algo_orders, 1):
                print(f"   {i}. Algo ID: {order.get('algoId')}")
                print(f"      Symbol: {order.get('instId')}")
                print(f"      Type: {order.get('ordType')}")
                print(f"      Side: {order.get('side')}")
                print(f"      Size: {order.get('sz')}")
                print(f"      State: {order.get('state')}")
                print()

        except Exception as e:
            print(f"❌ Ошибка получения всех алгоритмических ордеров: {e}")

        # 3. ПРОВЕРКА ОТКРЫТЫХ ОРДЕРОВ
        print(f"\n📋 ОТКРЫТЫЕ ОРДЕРА:")
        print("-" * 50)

        try:
            open_orders = await bot.client.get_open_orders()
            if isinstance(open_orders, list):
                orders_data = open_orders
            else:
                orders_data = open_orders.get("data", [])

            print(f"📊 Открытых ордеров: {len(orders_data)}")

            for i, order in enumerate(orders_data, 1):
                order_id = order.id if hasattr(order, "id") else order.get("ordId")
                symbol = (
                    order.symbol if hasattr(order, "symbol") else order.get("instId")
                )
                side = order.side if hasattr(order, "side") else order.get("side")
                order_type = (
                    order.type if hasattr(order, "type") else order.get("ordType")
                )

                print(f"   {i}. ID: {order_id}")
                print(f"      Symbol: {symbol}")
                print(f"      Side: {side}")
                print(f"      Type: {order_type}")
                print()

        except Exception as e:
            print(f"❌ Ошибка получения открытых ордеров: {e}")

        await bot.shutdown()
        print("\n✅ Тест завершен")

        return True

    except Exception as e:
        print(f"❌ Ошибка теста: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(test_oco_orders_fix())
