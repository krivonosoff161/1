import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
Диагностика OCO ордеров
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def debug_oco_orders():
    """Диагностика OCO ордеров"""
    print("🔍 ДИАГНОСТИКА OCO ОРДЕРОВ")
    print("=" * 50)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем обычные ордера
            print("\n1️⃣ ОБЫЧНЫЕ ОРДЕРА:")
            print("-" * 30)
            try:
                open_orders = await client.get_open_orders(symbol="BTC-USDT")
                if isinstance(open_orders, list):
                    print(f"   Обычных ордеров: {len(open_orders)}")
                    for order in open_orders:
                        print(
                            f"   Order ID: {order.get('ordId')}, State: {order.get('state')}, Type: {order.get('ordType')}"
                        )
                else:
                    print(f"   Обычных ордеров: {len(open_orders.get('data', []))}")
                    for order in open_orders.get("data", []):
                        print(
                            f"   Order ID: {order.get('ordId')}, State: {order.get('state')}, Type: {order.get('ordType')}"
                        )
            except Exception as e:
                print(f"   Ошибка получения обычных ордеров: {e}")

            # 2. Проверяем алгоритмические ордера
            print("\n2️⃣ АЛГОРИТМИЧЕСКИЕ ОРДЕРА:")
            print("-" * 30)
            try:
                algo_orders = await client.get_algo_orders()
                if isinstance(algo_orders, list):
                    print(f"   Алгоритмических ордеров: {len(algo_orders)}")
                    for order in algo_orders:
                        print(
                            f"   Algo ID: {order.get('algoId')}, State: {order.get('state')}, Type: {order.get('ordType')}"
                        )
                        if order.get("ordType") == "oco":
                            print(
                                f"     OCO Order: TP={order.get('tpTriggerPx')}, SL={order.get('slTriggerPx')}"
                            )
                else:
                    print(
                        f"   Алгоритмических ордеров: {len(algo_orders.get('data', []))}"
                    )
                    for order in algo_orders.get("data", []):
                        print(
                            f"   Algo ID: {order.get('algoId')}, State: {order.get('state')}, Type: {order.get('ordType')}"
                        )
                        if order.get("ordType") == "oco":
                            print(
                                f"     OCO Order: TP={order.get('tpTriggerPx')}, SL={order.get('slTriggerPx')}"
                            )
            except Exception as e:
                print(f"   Ошибка получения алгоритмических ордеров: {e}")

            # 3. Проверяем историю ордеров
            print("\n3️⃣ ИСТОРИЯ ОРДЕРОВ:")
            print("-" * 30)
            try:
                # Используем прямой API вызов
                order_history = await client._make_request(
                    "GET",
                    "/trade/orders-history",
                    params={"instType": "SPOT", "instId": "BTC-USDT"},
                )
                if order_history.get("data"):
                    recent_orders = order_history["data"][:5]
                    print(f"   Последние 5 ордеров:")
                    for order in recent_orders:
                        print(
                            f"   Order ID: {order.get('ordId')}, State: {order.get('state')}, Type: {order.get('ordType')}"
                        )
                else:
                    print("   История ордеров пуста")
            except Exception as e:
                print(f"   Ошибка получения истории ордеров: {e}")

            # 4. Анализ проблемы
            print("\n4️⃣ АНАЛИЗ ПРОБЛЕМЫ:")
            print("-" * 30)

            algo_count = 0
            if isinstance(algo_orders, list):
                algo_count = len(algo_orders)
            else:
                algo_count = len(algo_orders.get("data", []))

            if algo_count == 0:
                print("❌ ПРОБЛЕМА: Нет алгоритмических ордеров")
                print("   ВОЗМОЖНЫЕ ПРИЧИНЫ:")
                print("   1. OCO ордера не создаются")
                print("   2. OCO ордера сразу исполняются")
                print("   3. OCO ордера находятся в другом месте")
            else:
                print("✅ Алгоритмические ордера найдены")

            # 5. Рекомендации
            print("\n5️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)
            print("1. Проверить создание OCO ордеров в коде")
            print("2. Проверить правильность API вызовов")
            print("3. Добавить задержку между созданием и проверкой")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_oco_orders())
