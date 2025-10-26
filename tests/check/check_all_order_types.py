import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

"""
ПРОВЕРКА ВСЕХ ТИПОВ ОРДЕРОВ
Проверяем: Market, Limit, OCO, Algo, Positions
"""

import asyncio
import sys
from datetime import datetime

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def check_all_order_types():
    """Проверка всех типов ордеров на бирже"""
    print("🔍 ПОЛНАЯ ПРОВЕРКА ВСЕХ ОРДЕРОВ")
    print("=" * 60)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ОТКРЫТЫЕ ОРДЕРА (обычные)
        print(f"\n📋 ОТКРЫТЫЕ ОРДЕРА (обычные):")
        print("-" * 50)

        try:
            open_orders = await bot.client.get_open_orders()
            if isinstance(open_orders, list):
                orders_data = open_orders
            else:
                orders_data = open_orders.get("data", [])

            print(f"📊 Обычных ордеров: {len(orders_data)}")
            for i, order in enumerate(orders_data, 1):
                order_id = order.id if hasattr(order, "id") else order.get("ordId")
                symbol = (
                    order.symbol if hasattr(order, "symbol") else order.get("instId")
                )
                side = order.side if hasattr(order, "side") else order.get("side")
                order_type = (
                    order.type if hasattr(order, "type") else order.get("ordType")
                )
                price = order.price if hasattr(order, "price") else order.get("px")
                size = order.size if hasattr(order, "size") else order.get("sz")

                print(f"   {i}. ID: {order_id}")
                print(f"      Symbol: {symbol}")
                print(f"      Side: {side}")
                print(f"      Type: {order_type}")
                print(f"      Price: {price}")
                print(f"      Size: {size}")
                print()
        except Exception as e:
            print(f"❌ Ошибка получения открытых ордеров: {e}")

        # 2. АЛГОРИТМИЧЕСКИЕ ОРДЕРА (OCO, TP/SL)
        print(f"🤖 АЛГОРИТМИЧЕСКИЕ ОРДЕРА (OCO, TP/SL):")
        print("-" * 50)

        try:
            # Проверяем все типы algo ордеров
            algo_types = ["oco", "conditional", "trigger"]

            for algo_type in algo_types:
                print(f"   Проверяем {algo_type.upper()} ордера...")
                algo_orders = await bot.client.get_algo_orders(algo_type=algo_type)
                print(f"   📊 {algo_type.upper()}: {len(algo_orders)} ордеров")

                for i, order in enumerate(algo_orders, 1):
                    algo_id = order.get("algoId", "N/A")
                    symbol = order.get("instId", "N/A")
                    order_type = order.get("ordType", "N/A")
                    side = order.get("side", "N/A")
                    size = order.get("sz", "N/A")
                    tp_price = order.get("tpTriggerPx", "N/A")
                    sl_price = order.get("slTriggerPx", "N/A")
                    state = order.get("state", "N/A")

                    print(f"      {i}. Algo ID: {algo_id}")
                    print(f"         Symbol: {symbol}")
                    print(f"         Type: {order_type}")
                    print(f"         Side: {side}")
                    print(f"         Size: {size}")
                    print(f"         TP: {tp_price}")
                    print(f"         SL: {sl_price}")
                    print(f"         State: {state}")
                    print()
        except Exception as e:
            print(f"❌ Ошибка получения алгоритмических ордеров: {e}")

        # 3. ПОЗИЦИИ
        print(f"💼 АКТИВНЫЕ ПОЗИЦИИ:")
        print("-" * 50)

        try:
            positions = await bot.client.get_positions()
            print(f"📊 Позиций: {len(positions)}")

            for i, pos in enumerate(positions, 1):
                symbol = pos.get("instId", "N/A")
                side = pos.get("posSide", "N/A")
                size = pos.get("pos", "N/A")
                avg_price = pos.get("avgPx", "N/A")
                upl = pos.get("upl", "N/A")

                print(f"   {i}. Symbol: {symbol}")
                print(f"      Side: {side}")
                print(f"      Size: {size}")
                print(f"      Avg Price: {avg_price}")
                print(f"      Unrealized PnL: {upl}")
                print()
        except Exception as e:
            print(f"❌ Ошибка получения позиций: {e}")

        # 4. ИСТОРИЯ ОРДЕРОВ (последние)
        print(f"📜 ИСТОРИЯ ОРДЕРОВ (последние 20):")
        print("-" * 50)

        try:
            # Проверяем историю для ETH-USDT
            history = await bot.client.get_orders_history("ETH-USDT", limit=20)
            print(f"📊 История ETH-USDT: {len(history)} ордеров")

            for i, order in enumerate(history[:10], 1):  # Показываем первые 10
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

                print(f"   {i}. ID: {order_id}")
                print(f"      Symbol: {symbol}")
                print(f"      Side: {side}")
                print(f"      Type: {order_type}")
                print(f"      Size: {size}")
                print(f"      Price: {price}")
                print(f"      State: {state}")
                print(f"      Fill Size: {fill_size}")
                print(f"      Fill Price: {fill_price}")
                print(f"      Time: {c_time}")
                print()
        except Exception as e:
            print(f"❌ Ошибка получения истории: {e}")

        # 5. ПРЯМОЙ ЗАПРОС К API
        print(f"🔧 ПРЯМОЙ ЗАПРОС К API:")
        print("-" * 50)

        try:
            # Прямой запрос к API для получения всех ордеров
            import aiohttp

            headers = {
                "OK-ACCESS-KEY": bot.client.api_key,
                "OK-ACCESS-SIGN": "dummy",  # Для sandbox не нужна подпись
                "OK-ACCESS-TIMESTAMP": str(int(datetime.now().timestamp() * 1000)),
                "OK-ACCESS-PASSPHRASE": bot.client.passphrase,
                "Content-Type": "application/json",
            }

            if bot.client.sandbox:
                headers["x-simulated-trading"] = "1"

            # Запрос всех ордеров
            url = f"{bot.client.base_url}/api/v5/trade/orders-pending"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    result = await response.json()
                    print(f"📊 Прямой API ответ:")
                    print(f"   Code: {result.get('code')}")
                    print(f"   Message: {result.get('msg')}")
                    print(f"   Data: {result.get('data', [])}")
                    print(f"   Количество ордеров: {len(result.get('data', []))}")

                    for i, order in enumerate(result.get("data", []), 1):
                        print(f"      {i}. {order}")
                        print()

        except Exception as e:
            print(f"❌ Ошибка прямого запроса: {e}")

        await bot.shutdown()
        print("✅ Проверка завершена")

        return True

    except Exception as e:
        print(f"❌ Ошибка проверки: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(check_all_order_types())
