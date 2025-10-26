#!/usr/bin/env python3
"""
Тест после исправления режима торговли
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def test_after_fix():
    """Тест после исправления режима торговли"""
    print("🧪 ТЕСТ ПОСЛЕ ИСПРАВЛЕНИЯ РЕЖИМА ТОРГОВЛИ")
    print("=" * 60)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем режим
            print("\n1️⃣ ПРОВЕРКА РЕЖИМА:")
            print("-" * 30)
            account_config = await client.get_account_config()
            pos_mode = account_config.get("posMode", "N/A")
            print(f"   Position Mode: {pos_mode}")

            if pos_mode == "net_mode":
                print("✅ РЕЖИМ ИСПРАВЛЕН! Position Mode = net_mode (SPOT)")
            elif pos_mode == "long_short_mode":
                print("❌ РЕЖИМ НЕ ИСПРАВЛЕН! Position Mode = long_short_mode (MARGIN)")
                print("   НУЖНО: Переключить на Net в OKX")
                return
            else:
                print(f"⚠️ Неизвестный режим: {pos_mode}")

            # 2. Проверяем займы
            print("\n2️⃣ ПРОВЕРКА ЗАЙМОВ:")
            print("-" * 30)
            btc_borrowed = await client.get_borrowed_balance("BTC")
            usdt_borrowed = await client.get_borrowed_balance("USDT")
            print(f"   BTC займ: {btc_borrowed}")
            print(f"   USDT займ: {usdt_borrowed}")

            if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
                print("❌ Есть займы - блокирует торговлю")
                return
            else:
                print("✅ Займов нет")

            # 3. Тест размещения ордера
            print("\n3️⃣ ТЕСТ РАЗМЕЩЕНИЯ ОРДЕРА:")
            print("-" * 30)
            try:
                # Пробуем разместить тестовый ордер
                test_order = await client.place_order(
                    inst_id="BTC-USDT",
                    side="buy",
                    order_type="LIMIT",
                    quantity="0.0001",
                    price="50000",
                    post_only=True,
                )
                print("✅ Тестовый ордер размещен успешно")
                print(
                    f"   Order ID: {test_order.get('data', [{}])[0].get('ordId', 'N/A')}"
                )

                # Отменяем тестовый ордер
                if test_order.get("data"):
                    order_id = test_order["data"][0]["ordId"]
                    await client.cancel_order("BTC-USDT", order_id)
                    print("✅ Тестовый ордер отменен")

                print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
                print("   Бот готов к работе!")
                print("   Запустите: python test_full_trading_system.py")

            except Exception as e:
                print(f"❌ Ошибка размещения ордера: {e}")
                print("   Возможно, нужно подождать несколько минут")
                print("   после изменения настроек в OKX")

    except Exception as e:
        print(f"❌ Ошибка теста: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_after_fix())
