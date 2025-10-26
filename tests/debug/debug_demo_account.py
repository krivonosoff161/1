import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
Диагностика демо аккаунта
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def debug_demo_account():
    """Диагностика демо аккаунта"""
    print("🔍 ДИАГНОСТИКА ДЕМО АККАУНТА")
    print("=" * 50)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем конфигурацию аккаунта
            print("\n1️⃣ КОНФИГУРАЦИЯ АККАУНТА:")
            print("-" * 30)
            account_config = await client.get_account_config()
            print(f"   Account Level: {account_config.get('acctLv', 'N/A')}")
            print(f"   Position Mode: {account_config.get('posMode', 'N/A')}")
            print(f"   Auto Loan: {account_config.get('autoLoan', 'N/A')}")
            print(f"   Level: {account_config.get('level', 'N/A')}")
            print(f"   Level Temporary: {account_config.get('levelTmp', 'N/A')}")

            # 2. Проверяем полный ответ API
            print("\n2️⃣ ПОЛНЫЙ ОТВЕТ API:")
            print("-" * 30)
            try:
                result = await client._make_request("GET", "/account/config")
                print(f"   Полный ответ: {result}")
            except Exception as e:
                print(f"   Ошибка запроса: {e}")

            # 3. Анализ проблемы
            print("\n3️⃣ АНАЛИЗ ПРОБЛЕМЫ:")
            print("-" * 30)

            if account_config.get("acctLv") == "1":
                print("✅ Account Level: 1 (Simple mode - SPOT only)")
            else:
                print(f"❌ Account Level: {account_config.get('acctLv')} (Margin mode)")

            if account_config.get("posMode") == "net_mode":
                print("✅ Position Mode: net_mode (SPOT)")
            elif account_config.get("posMode") == "long_short_mode":
                print("❌ Position Mode: long_short_mode (MARGIN)")
                print("   ПРОБЛЕМА: Демо аккаунт может иметь MARGIN режим по умолчанию")
            else:
                print(f"⚠️ Position Mode: {account_config.get('posMode')} (Unknown)")

            # 4. Проверяем займы
            print("\n4️⃣ ПРОВЕРКА ЗАЙМОВ:")
            print("-" * 30)
            btc_borrowed = await client.get_borrowed_balance("BTC")
            usdt_borrowed = await client.get_borrowed_balance("USDT")
            print(f"   BTC займ: {btc_borrowed}")
            print(f"   USDT займ: {usdt_borrowed}")

            if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
                print("❌ Есть займы - блокирует торговлю")
            else:
                print("✅ Займов нет")

            # 5. Рекомендации
            print("\n5️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)

            if account_config.get("posMode") == "long_short_mode":
                print("🔧 ПРОБЛЕМА: Демо аккаунт в MARGIN режиме")
                print("   РЕШЕНИЕ 1: Отключить проверку займов в боте")
                print("   РЕШЕНИЕ 2: Переключить на реальный аккаунт")
                print("   РЕШЕНИЕ 3: Игнорировать Position Mode для демо")

            # 6. Тест размещения ордера
            print("\n6️⃣ ТЕСТ РАЗМЕЩЕНИЯ ОРДЕРА:")
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

                print("\n🎉 ОРДЕРА РАБОТАЮТ!")
                print("   Проблема только в проверке займов")

            except Exception as e:
                print(f"❌ Ошибка размещения ордера: {e}")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_demo_account())
