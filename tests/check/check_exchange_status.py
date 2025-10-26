import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

"""
ПРОВЕРКА ТЕКУЩЕГО СОСТОЯНИЯ НА БИРЖЕ
Проверяем все типы ордеров: Market, Limit, TP/SL
"""

import asyncio
import sys
from datetime import datetime

from loguru import logger

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def check_exchange_status():
    """Проверка всех ордеров на бирже"""
    print("🔍 ПРОВЕРКА СОСТОЯНИЯ НА БИРЖЕ")
    print("=" * 60)

    try:
        # Инициализация
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ПРОВЕРКА ОТКРЫТЫХ ОРДЕРОВ
        print(f"\n📋 ОТКРЫТЫЕ ОРДЕРА:")
        print("-" * 40)

        open_orders = await bot.client.get_open_orders()
        print(
            f"📊 Всего открытых ордеров: {len(open_orders) if isinstance(open_orders, list) else len(open_orders.get('data', []))}"
        )

        if isinstance(open_orders, list):
            orders_data = open_orders
        else:
            orders_data = open_orders.get("data", [])

        for i, order in enumerate(orders_data, 1):
            # Проверяем тип объекта
            if hasattr(order, "get"):
                # Это словарь
                print(f"   {i}. ID: {order.get('ordId', 'N/A')}")
                print(f"      Symbol: {order.get('instId', 'N/A')}")
                print(f"      Side: {order.get('side', 'N/A')}")
                print(f"      Type: {order.get('ordType', 'N/A')}")
                print(f"      Size: {order.get('sz', 'N/A')}")
                print(f"      Price: {order.get('px', 'N/A')}")
                print(f"      State: {order.get('state', 'N/A')}")
                print(f"      Time: {order.get('cTime', 'N/A')}")
            else:
                # Это объект Order
                print(f"   {i}. ID: {getattr(order, 'id', 'N/A')}")
                print(f"      Symbol: {getattr(order, 'symbol', 'N/A')}")
                print(f"      Side: {getattr(order, 'side', 'N/A')}")
                print(f"      Type: {getattr(order, 'type', 'N/A')}")
                print(f"      Size: {getattr(order, 'size', 'N/A')}")
                print(f"      Price: {getattr(order, 'price', 'N/A')}")
                print(f"      State: {getattr(order, 'state', 'N/A')}")
                print(f"      Time: {getattr(order, 'timestamp', 'N/A')}")
            print()

        # 2. ПРОВЕРКА АЛГОРИТМИЧЕСКИХ ОРДЕРОВ (TP/SL)
        print(f"🤖 АЛГОРИТМИЧЕСКИЕ ОРДЕРА (TP/SL):")
        print("-" * 40)

        algo_orders = await bot.client.get_algo_orders()
        print(f"📊 Всего алгоритмических ордеров: {len(algo_orders)}")

        for i, order in enumerate(algo_orders, 1):
            print(f"   {i}. Algo ID: {order.get('algoId', 'N/A')}")
            print(f"      Symbol: {order.get('instId', 'N/A')}")
            print(f"      Type: {order.get('ordType', 'N/A')}")
            print(f"      Side: {order.get('side', 'N/A')}")
            print(f"      Size: {order.get('sz', 'N/A')}")
            print(f"      TP Price: {order.get('tpTriggerPx', 'N/A')}")
            print(f"      SL Price: {order.get('slTriggerPx', 'N/A')}")
            print(f"      State: {order.get('state', 'N/A')}")
            print(f"      Time: {order.get('cTime', 'N/A')}")
            print()

        # 3. ПРОВЕРКА ПОЗИЦИЙ
        print(f"💼 АКТИВНЫЕ ПОЗИЦИИ:")
        print("-" * 40)

        positions = await bot.client.get_positions()
        print(f"📊 Всего позиций: {len(positions)}")

        for i, pos in enumerate(positions, 1):
            print(f"   {i}. Symbol: {pos.get('instId', 'N/A')}")
            print(f"      Side: {pos.get('posSide', 'N/A')}")
            print(f"      Size: {pos.get('pos', 'N/A')}")
            print(f"      Avg Price: {pos.get('avgPx', 'N/A')}")
            print(f"      Unrealized PnL: {pos.get('upl', 'N/A')}")
            print()

        # 4. ПРОВЕРКА ЗАЙМОВ
        print(f"💰 ПРОВЕРКА ЗАЙМОВ:")
        print("-" * 40)

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

        # 5. ПРОВЕРКА БАЛАНСА
        print(f"\n💳 ТЕКУЩИЙ БАЛАНС:")
        print("-" * 40)

        balances = await bot.client.get_account_balance()
        for balance in balances:
            if balance.currency in ["ETH", "USDT", "BTC"]:
                print(
                    f"   {balance.currency}: {balance.free:.8f} (free) | {balance.used:.8f} (used)"
                )

        # 6. ИСТОРИЯ ОРДЕРОВ (последние 10)
        print(f"\n📜 ПОСЛЕДНИЕ ОРДЕРА (история):")
        print("-" * 40)

        order_history = await bot.client.get_order_history("ETH-USDT", limit=10)
        print(f"📊 Последних ордеров ETH-USDT: {len(order_history)}")

        for i, order in enumerate(order_history[:5], 1):  # Показываем только первые 5
            print(f"   {i}. ID: {order.get('ordId', 'N/A')}")
            print(f"      Side: {order.get('side', 'N/A')}")
            print(f"      Type: {order.get('ordType', 'N/A')}")
            print(f"      Size: {order.get('sz', 'N/A')}")
            print(f"      Price: {order.get('px', 'N/A')}")
            print(f"      State: {order.get('state', 'N/A')}")
            print(f"      Time: {order.get('cTime', 'N/A')}")
            print()

        await bot.shutdown()
        print("✅ Проверка завершена")

        return True

    except Exception as e:
        print(f"❌ Ошибка проверки: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(check_exchange_status())
