#!/usr/bin/env python3
"""
Диагностика займов в демо аккаунте
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def debug_demo_borrowing():
    """Диагностика займов в демо аккаунте"""
    print("🔍 ДИАГНОСТИКА ЗАЙМОВ В ДЕМО АККАУНТЕ")
    print("=" * 60)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем займы ДО сделки
            print("\n1️⃣ ЗАЙМЫ ДО СДЕЛКИ:")
            print("-" * 30)
            btc_borrowed_before = await client.get_borrowed_balance("BTC")
            usdt_borrowed_before = await client.get_borrowed_balance("USDT")
            print(f"   BTC займ: {btc_borrowed_before}")
            print(f"   USDT займ: {usdt_borrowed_before}")

            # 2. Размещаем тестовый ордер
            print("\n2️⃣ РАЗМЕЩЕНИЕ ТЕСТОВОГО ОРДЕРА:")
            print("-" * 30)
            try:
                # Получаем текущую цену
                ticker = await client.get_ticker("BTC-USDT")
                current_price = float(ticker.get("last", 0))
                print(f"   Текущая цена: ${current_price:,.2f}")

                # Размещаем ордер
                test_order = await client.place_order(
                    inst_id="BTC-USDT",
                    side="buy",
                    order_type="LIMIT",
                    quantity="0.0001",
                    price=str(current_price * 0.99),  # Ниже рынка
                    post_only=True,
                )

                if test_order.get("data"):
                    order_id = test_order["data"][0]["ordId"]
                    print(f"   ✅ Ордер размещен: {order_id}")

                    # 3. Проверяем займы ПОСЛЕ сделки
                    print("\n3️⃣ ЗАЙМЫ ПОСЛЕ СДЕЛКИ:")
                    print("-" * 30)
                    await asyncio.sleep(1)  # Небольшая задержка

                    btc_borrowed_after = await client.get_borrowed_balance("BTC")
                    usdt_borrowed_after = await client.get_borrowed_balance("USDT")
                    print(f"   BTC займ: {btc_borrowed_after}")
                    print(f"   USDT займ: {usdt_borrowed_after}")

                    # 4. Анализ изменений
                    print("\n4️⃣ АНАЛИЗ ИЗМЕНЕНИЙ:")
                    print("-" * 30)
                    btc_change = float(btc_borrowed_after) - float(btc_borrowed_before)
                    usdt_change = float(usdt_borrowed_after) - float(
                        usdt_borrowed_before
                    )

                    if btc_change > 0 or usdt_change > 0:
                        print("🚨 ПРОБЛЕМА: Займы увеличились после размещения ордера!")
                        print(f"   BTC изменение: {btc_change}")
                        print(f"   USDT изменение: {usdt_change}")
                        print("\n   ПРИЧИНА: Демо аккаунт автоматически берет займы")
                        print(
                            "   РЕШЕНИЕ: Нужно принудительно погасить займы после каждой сделки"
                        )
                    else:
                        print("✅ Займы не изменились")

                    # Отменяем ордер
                    await client.cancel_order("BTC-USDT", order_id)
                    print(f"   ✅ Ордер отменен: {order_id}")

                else:
                    print("   ❌ Ордер не размещен")

            except Exception as e:
                print(f"   ❌ Ошибка размещения ордера: {e}")

            # 5. Рекомендации
            print("\n5️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)
            print("1. Демо аккаунт автоматически берет займы")
            print("2. Нужно принудительно погашать займы после каждой сделки")
            print("3. Добавить автоматическое погашение займов")
            print("4. Или полностью отключить торговлю для демо")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_demo_borrowing())
