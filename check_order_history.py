"""
ПРОВЕРКА ИСТОРИИ ОРДЕРОВ
Проверяем что произошло с OCO ордерами
"""

import asyncio
import sys
from datetime import datetime, timedelta

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def check_order_history():
    """Проверка истории ордеров"""
    print("📜 ПРОВЕРКА ИСТОРИИ ОРДЕРОВ")
    print("=" * 60)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ПРОВЕРКА ИСТОРИИ ОРДЕРОВ ETH-USDT
        print(f"\n📜 ИСТОРИЯ ОРДЕРОВ ETH-USDT:")
        print("-" * 50)

        try:
            # Получаем историю ордеров за последние 2 часа
            history = await bot.client.get_orders_history("ETH-USDT", limit=50)
            print(f"📊 История ордеров: {len(history)}")

            # Фильтруем ордера за последние 2 часа
            two_hours_ago = datetime.now() - timedelta(hours=2)
            recent_orders = []

            for order in history:
                order_time = datetime.fromtimestamp(int(order.get("cTime", 0)) / 1000)
                if order_time > two_hours_ago:
                    recent_orders.append(order)

            print(f"📊 За последние 2 часа: {len(recent_orders)}")

            for i, order in enumerate(recent_orders, 1):
                order_id = order.get("ordId", "N/A")
                symbol = order.get("instId", "N/A")
                side = order.get("side", "N/A")
                order_type = order.get("ordType", "N/A")
                size = order.get("sz", "N/A")
                price = order.get("px", "N/A")
                state = order.get("state", "N/A")
                fill_size = order.get("fillSz", "N/A")
                fill_price = order.get("fillPx", "N/A")
                c_time = order.get("cTime", "N/A")

                # Конвертируем время
                if c_time != "N/A":
                    order_time = datetime.fromtimestamp(int(c_time) / 1000)
                    time_str = order_time.strftime("%H:%M:%S")
                else:
                    time_str = "N/A"

                print(f"   {i}. ID: {order_id}")
                print(f"      Symbol: {symbol}")
                print(f"      Side: {side}")
                print(f"      Type: {order_type}")
                print(f"      Size: {size}")
                print(f"      Price: {price}")
                print(f"      State: {state}")
                print(f"      Fill Size: {fill_size}")
                print(f"      Fill Price: {fill_price}")
                print(f"      Time: {time_str}")
                print()

        except Exception as e:
            print(f"❌ Ошибка получения истории: {e}")

        # 2. ПРОВЕРКА ТЕКУЩЕГО СОСТОЯНИЯ
        print(f"\n🔍 ТЕКУЩЕЕ СОСТОЯНИЕ:")
        print("-" * 50)

        try:
            # Открытые ордера
            open_orders = await bot.client.get_open_orders()
            if isinstance(open_orders, list):
                orders_data = open_orders
            else:
                orders_data = open_orders.get("data", [])

            print(f"📊 Открытых ордеров: {len(orders_data)}")

            # Алгоритмические ордера
            algo_orders = await bot.client.get_algo_orders()
            print(f"📊 Алгоритмических ордеров: {len(algo_orders)}")

            # Позиции
            positions = await bot.client.get_positions()
            print(f"📊 Позиций: {len(positions)}")

            # Займы
            eth_borrowed = await bot.client.get_borrowed_balance("ETH")
            usdt_borrowed = await bot.client.get_borrowed_balance("USDT")
            print(f"📊 ETH займы: {eth_borrowed:.8f}")
            print(f"📊 USDT займы: {usdt_borrowed:.2f}")

        except Exception as e:
            print(f"❌ Ошибка проверки состояния: {e}")

        await bot.shutdown()
        print("\n✅ Проверка истории завершена")

        return True

    except Exception as e:
        print(f"❌ Ошибка проверки истории: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(check_order_history())
