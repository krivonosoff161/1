"""
ФИНАЛЬНАЯ ПРОВЕРКА БИРЖИ
Используем наш клиент для проверки всех ордеров
"""

import asyncio
import sys
from datetime import datetime

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def final_exchange_check():
    """Финальная проверка всех ордеров на бирже"""
    print("🔍 ФИНАЛЬНАЯ ПРОВЕРКА БИРЖИ")
    print("=" * 60)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ОТКРЫТЫЕ ОРДЕРА
        print(f"\n📋 ОТКРЫТЫЕ ОРДЕРА:")
        print("-" * 50)

        try:
            open_orders = await bot.client.get_open_orders()
            print(f"📊 Тип ответа: {type(open_orders)}")

            if isinstance(open_orders, list):
                orders_data = open_orders
                print(f"📊 Список ордеров: {len(orders_data)}")
            else:
                orders_data = open_orders.get("data", [])
                print(f"📊 Словарь с data: {len(orders_data)}")

            for i, order in enumerate(orders_data, 1):
                print(f"   {i}. Тип объекта: {type(order)}")
                if hasattr(order, "__dict__"):
                    print(f"      Атрибуты: {list(order.__dict__.keys())}")
                if hasattr(order, "get"):
                    print(f"      Ключи: {list(order.keys())}")
                print(f"      Объект: {order}")
                print()

        except Exception as e:
            print(f"❌ Ошибка получения открытых ордеров: {e}")

        # 2. АЛГОРИТМИЧЕСКИЕ ОРДЕРА
        print(f"\n🤖 АЛГОРИТМИЧЕСКИЕ ОРДЕРА:")
        print("-" * 50)

        try:
            algo_orders = await bot.client.get_algo_orders()
            print(f"📊 Алгоритмических ордеров: {len(algo_orders)}")

            for i, order in enumerate(algo_orders, 1):
                print(f"   {i}. {order}")
                print()

        except Exception as e:
            print(f"❌ Ошибка получения алгоритмических ордеров: {e}")

        # 3. ПОЗИЦИИ
        print(f"\n💼 ПОЗИЦИИ:")
        print("-" * 50)

        try:
            positions = await bot.client.get_positions()
            print(f"📊 Позиций: {len(positions)}")

            for i, pos in enumerate(positions, 1):
                print(f"   {i}. {pos}")
                print()

        except Exception as e:
            print(f"❌ Ошибка получения позиций: {e}")

        # 4. БАЛАНС
        print(f"\n💰 БАЛАНС:")
        print("-" * 50)

        try:
            balances = await bot.client.get_account_balance()
            print(f"📊 Балансов: {len(balances)}")

            for balance in balances:
                if balance.currency in ["ETH", "USDT", "BTC"]:
                    print(
                        f"   {balance.currency}: {balance.free:.8f} (free) | {balance.used:.8f} (used)"
                    )

        except Exception as e:
            print(f"❌ Ошибка получения баланса: {e}")

        # 5. ЗАЙМЫ
        print(f"\n🚨 ЗАЙМЫ:")
        print("-" * 50)

        try:
            eth_borrowed = await bot.client.get_borrowed_balance("ETH")
            usdt_borrowed = await bot.client.get_borrowed_balance("USDT")
            btc_borrowed = await bot.client.get_borrowed_balance("BTC")

            print(f"   ETH займы: {eth_borrowed:.8f}")
            print(f"   USDT займы: {usdt_borrowed:.2f}")
            print(f"   BTC займы: {btc_borrowed:.8f}")

            if eth_borrowed > 0 or usdt_borrowed > 0 or btc_borrowed > 0:
                print("   🚨 ОБНАРУЖЕНЫ ЗАЙМЫ!")
            else:
                print("   ✅ Займов нет")

        except Exception as e:
            print(f"❌ Ошибка проверки займов: {e}")

        # 6. КОНФИГУРАЦИЯ АККАУНТА
        print(f"\n⚙️ КОНФИГУРАЦИЯ АККАУНТА:")
        print("-" * 50)

        try:
            account_config = await bot.client.get_account_config()
            print(f"📊 Конфигурация: {account_config}")

        except Exception as e:
            print(f"❌ Ошибка получения конфигурации: {e}")

        await bot.shutdown()
        print("\n✅ Финальная проверка завершена")

        return True

    except Exception as e:
        print(f"❌ Ошибка финальной проверки: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(final_exchange_check())
