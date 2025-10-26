import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
Диагностика POST-ONLY ордеров
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def debug_post_only():
    """Диагностика POST-ONLY ордеров"""
    print("🔍 ДИАГНОСТИКА POST-ONLY ОРДЕРОВ")
    print("=" * 50)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Получаем текущую цену
            print("\n1️⃣ ТЕКУЩАЯ ЦЕНА:")
            print("-" * 30)
            ticker = await client.get_ticker("BTC-USDT")
            current_price = float(ticker.get("last", 0))
            print(f"   Текущая цена: ${current_price:,.2f}")

            # 2. Тестируем разные отступы
            print("\n2️⃣ ТЕСТ РАЗНЫХ ОТСТУПОВ:")
            print("-" * 30)

            offsets = [
                0.0001,
                0.0005,
                0.001,
                0.005,
                0.01,
            ]  # 0.01%, 0.05%, 0.1%, 0.5%, 1%

            for offset in offsets:
                buy_price = current_price * (1 - offset)
                sell_price = current_price * (1 + offset)

                print(f"   Отступ {offset*100:.2f}%:")
                print(
                    f"     BUY: ${buy_price:,.2f} (отступ: ${current_price - buy_price:,.2f})"
                )
                print(
                    f"     SELL: ${sell_price:,.2f} (отступ: ${sell_price - current_price:,.2f})"
                )

                # Тестируем BUY ордер
                try:
                    test_order = await client.place_order(
                        inst_id="BTC-USDT",
                        side="buy",
                        order_type="LIMIT",
                        quantity="0.0001",
                        price=str(buy_price),
                        post_only=True,
                    )

                    if test_order.get("data"):
                        order_id = test_order["data"][0]["ordId"]
                        print(f"     ✅ BUY ордер размещен: {order_id}")

                        # Отменяем ордер
                        await client.cancel_order("BTC-USDT", order_id)
                        print(f"     ✅ BUY ордер отменен")
                    else:
                        print(f"     ❌ BUY ордер не размещен")

                except Exception as e:
                    print(f"     ❌ BUY ордер ошибка: {e}")

                print()

            # 3. Анализ проблемы
            print("\n3️⃣ АНАЛИЗ ПРОБЛЕМЫ:")
            print("-" * 30)
            print("   POST-ONLY ордера должны быть:")
            print("   - BUY: ниже рыночной цены")
            print("   - SELL: выше рыночной цены")
            print("   - Достаточно далеко от рынка")

            # 4. Рекомендации
            print("\n4️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)
            print("1. Увеличить отступ от рыночной цены")
            print("2. Использовать более агрессивные цены")
            print("3. Добавить проверку минимального отступа")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_post_only())
