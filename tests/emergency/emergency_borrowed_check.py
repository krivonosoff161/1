import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
ЭКСТРЕННАЯ ПРОВЕРКА ЗАЙМОВ
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def emergency_borrowed_check():
    """Экстренная проверка займов"""
    print("🚨 ЭКСТРЕННАЯ ПРОВЕРКА ЗАЙМОВ")
    print("=" * 50)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем займы
            print("\n1️⃣ ПРОВЕРКА ЗАЙМОВ:")
            print("-" * 30)
            btc_borrowed = await client.get_borrowed_balance("BTC")
            usdt_borrowed = await client.get_borrowed_balance("USDT")
            print(f"   BTC займ: {btc_borrowed}")
            print(f"   USDT займ: {usdt_borrowed}")

            if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
                print("🚨 КРИТИЧЕСКАЯ ПРОБЛЕМА: ЕСТЬ ЗАЙМЫ!")
                print("   Бот должен был их заблокировать!")
            else:
                print("✅ Займов нет")

            # 2. Проверяем конфигурацию аккаунта
            print("\n2️⃣ КОНФИГУРАЦИЯ АККАУНТА:")
            print("-" * 30)
            account_config = await client.get_account_config()
            print(f"   Account Level: {account_config.get('acctLv')}")
            print(f"   Position Mode: {account_config.get('posMode')}")
            print(f"   Auto Loan: {account_config.get('autoLoan')}")

            # 3. Проверяем логику бота
            print("\n3️⃣ ЛОГИКА БОТА:")
            print("-" * 30)
            if (
                account_config.get("acctLv") == "1"
                and account_config.get("posMode") == "long_short_mode"
            ):
                print("✅ Демо аккаунт с MARGIN режимом - проверка займов ОТКЛЮЧЕНА")
                print("   Это правильно для демо аккаунта")
            else:
                print("❌ ПРОБЛЕМА: Не демо аккаунт, но проверка займов отключена!")
                print("   Нужно включить проверку займов для реальных аккаунтов")

            # 4. Проверяем последние ордера
            print("\n4️⃣ ПОСЛЕДНИЕ ОРДЕРА:")
            print("-" * 30)
            try:
                # Получаем историю ордеров
                order_history = await client._make_request(
                    "GET",
                    "/trade/orders-history",
                    params={"instType": "SPOT", "instId": "BTC-USDT"},
                )
                if order_history.get("data"):
                    recent_orders = order_history["data"][:3]
                    print(f"   Последние 3 ордера:")
                    for order in recent_orders:
                        print(
                            f"   Order ID: {order.get('ordId')}, State: {order.get('state')}, Type: {order.get('ordType')}"
                        )
                        print(
                            f"   Side: {order.get('side')}, Size: {order.get('sz')}, Price: {order.get('px')}"
                        )
                else:
                    print("   История ордеров пуста")
            except Exception as e:
                print(f"   Ошибка получения истории: {e}")

            # 5. Анализ проблемы
            print("\n5️⃣ АНАЛИЗ ПРОБЛЕМЫ:")
            print("-" * 30)

            if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
                print("🚨 ПРОБЛЕМА: Бот берет займы!")
                print("   ВОЗМОЖНЫЕ ПРИЧИНЫ:")
                print("   1. Проверка займов отключена для демо")
                print("   2. Бот не проверяет займы перед сделками")
                print("   3. API возвращает неправильные данные")
                print("   4. Логика проверки работает неправильно")

                print("\n🔧 РЕШЕНИЕ:")
                print("   1. ВРЕМЕННО включить проверку займов")
                print("   2. Проверить логику в коде")
                print("   3. Добавить дополнительную проверку")
            else:
                print("✅ Займов нет - проблема решена")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(emergency_borrowed_check())
