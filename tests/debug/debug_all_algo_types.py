"""
ОТЛАДКА ВСЕХ ТИПОВ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ
Проверяем все возможные типы и параметры
"""

import asyncio
import sys

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def debug_all_algo_types():
    """Отладка всех типов алгоритмических ордеров"""
    print("🔍 ОТЛАДКА ВСЕХ ТИПОВ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ")
    print("=" * 70)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ПРОВЕРКА БЕЗ ПАРАМЕТРОВ
        print(f"\n🤖 БЕЗ ПАРАМЕТРОВ:")
        print("-" * 50)

        try:
            all_orders = await bot.client.get_algo_orders()
            print(f"📊 Всего: {len(all_orders)}")
            for order in all_orders:
                print(f"   {order}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

        # 2. ПРОВЕРКА OCO
        print(f"\n🤖 OCO ОРДЕРА:")
        print("-" * 50)

        try:
            oco_orders = await bot.client.get_algo_orders(algo_type="oco")
            print(f"📊 OCO: {len(oco_orders)}")
            for order in oco_orders:
                print(f"   {order}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

        # 3. ПРОВЕРКА CONDITIONAL
        print(f"\n🤖 CONDITIONAL ОРДЕРА:")
        print("-" * 50)

        try:
            conditional_orders = await bot.client.get_algo_orders(
                algo_type="conditional"
            )
            print(f"📊 CONDITIONAL: {len(conditional_orders)}")
            for order in conditional_orders:
                print(f"   {order}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

        # 4. ПРОВЕРКА TRIGGER
        print(f"\n🤖 TRIGGER ОРДЕРА:")
        print("-" * 50)

        try:
            trigger_orders = await bot.client.get_algo_orders(algo_type="trigger")
            print(f"📊 TRIGGER: {len(trigger_orders)}")
            for order in trigger_orders:
                print(f"   {order}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

        # 5. ПРОВЕРКА С СИМВОЛОМ
        print(f"\n🤖 С СИМВОЛОМ ETH-USDT:")
        print("-" * 50)

        try:
            eth_orders = await bot.client.get_algo_orders(symbol="ETH-USDT")
            print(f"📊 ETH-USDT: {len(eth_orders)}")
            for order in eth_orders:
                print(f"   {order}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

        # 6. ПРОВЕРКА OCO С СИМВОЛОМ
        print(f"\n🤖 OCO С СИМВОЛОМ ETH-USDT:")
        print("-" * 50)

        try:
            eth_oco_orders = await bot.client.get_algo_orders(
                symbol="ETH-USDT", algo_type="oco"
            )
            print(f"📊 ETH-USDT OCO: {len(eth_oco_orders)}")
            for order in eth_oco_orders:
                print(f"   {order}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

        # 7. ПРОВЕРКА ОТКРЫТЫХ ОРДЕРОВ
        print(f"\n📋 ОТКРЫТЫЕ ОРДЕРА:")
        print("-" * 50)

        try:
            open_orders = await bot.client.get_open_orders()
            if isinstance(open_orders, list):
                orders_data = open_orders
            else:
                orders_data = open_orders.get("data", [])

            print(f"📊 Открытых: {len(orders_data)}")
            for order in orders_data:
                order_id = order.id if hasattr(order, "id") else order.get("ordId")
                symbol = (
                    order.symbol if hasattr(order, "symbol") else order.get("instId")
                )
                order_type = (
                    order.type if hasattr(order, "type") else order.get("ordType")
                )
                print(f"   ID: {order_id}, Symbol: {symbol}, Type: {order_type}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

        await bot.shutdown()
        print("\n✅ Отладка завершена")

        return True

    except Exception as e:
        print(f"❌ Ошибка отладки: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(debug_all_algo_types())
