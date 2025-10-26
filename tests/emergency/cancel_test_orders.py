import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

"""
ОТМЕНА ТЕСТОВЫХ ОРДЕРОВ
Отменяем все открытые LIMIT ордера от тестов
"""

import asyncio
import sys

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def cancel_test_orders():
    """Отмена всех тестовых ордеров"""
    print("🚨 ОТМЕНА ТЕСТОВЫХ ОРДЕРОВ")
    print("=" * 50)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        # Получаем открытые ордера
        open_orders = await bot.client.get_open_orders()

        if isinstance(open_orders, list):
            orders_data = open_orders
        else:
            orders_data = open_orders.get("data", [])

        print(f"📊 Найдено открытых ордеров: {len(orders_data)}")

        # Отменяем каждый ордер
        for i, order in enumerate(orders_data, 1):
            order_id = order.id if hasattr(order, "id") else order.get("ordId")
            symbol = order.symbol if hasattr(order, "symbol") else order.get("instId")

            print(f"   {i}. Отменяем ордер {order_id} ({symbol})...")

            try:
                result = await bot.client.cancel_order(symbol, order_id)
                if result.get("code") == "0":
                    print(f"      ✅ Ордер {order_id} отменен")
                else:
                    print(f"      ❌ Ошибка отмены: {result.get('msg')}")
            except Exception as e:
                print(f"      ❌ Ошибка: {e}")

        # Проверяем результат
        print(f"\n🔍 ПРОВЕРКА РЕЗУЛЬТАТА:")
        final_orders = await bot.client.get_open_orders()

        if isinstance(final_orders, list):
            final_count = len(final_orders)
        else:
            final_count = len(final_orders.get("data", []))

        if final_count == 0:
            print("✅ Все ордера отменены!")
        else:
            print(f"⚠️ Осталось ордеров: {final_count}")

        await bot.shutdown()
        return True

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(cancel_test_orders())
