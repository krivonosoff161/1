import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
Детальная диагностика режима торговли
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def check_trading_mode_detailed():
    """Детальная проверка режима торговли"""
    print("🔍 ДЕТАЛЬНАЯ ДИАГНОСТИКА РЕЖИМА ТОРГОВЛИ")
    print("=" * 60)

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

            # 2. Проверяем баланс и займы
            print("\n2️⃣ БАЛАНС И ЗАЙМЫ:")
            print("-" * 30)
            btc_balance = await client.get_balance("BTC")
            usdt_balance = await client.get_balance("USDT")
            btc_borrowed = await client.get_borrowed_balance("BTC")
            usdt_borrowed = await client.get_borrowed_balance("USDT")

            print(f"   BTC Balance: {btc_balance}")
            print(f"   USDT Balance: {usdt_balance}")
            print(f"   BTC Borrowed: {btc_borrowed}")
            print(f"   USDT Borrowed: {usdt_borrowed}")

            # 3. Проверяем настройки бота
            print("\n3️⃣ НАСТРОЙКИ БОТА:")
            print("-" * 30)
            print(f"   Trading Mode: {config.trading.mode}")
            print(f"   Symbols: {config.trading.symbols}")
            print(f"   Risk Management: {config.risk.max_daily_loss}%")

            # 4. Анализ проблемы
            print("\n4️⃣ АНАЛИЗ ПРОБЛЕМЫ:")
            print("-" * 30)

            # Проверяем режим аккаунта
            if account_config.get("acctLv") == "1":
                print("✅ Account Level: 1 (Simple mode - SPOT only)")
            else:
                print(f"❌ Account Level: {account_config.get('acctLv')} (Margin mode)")

            # Проверяем режим позиций
            if account_config.get("posMode") == "net_mode":
                print("✅ Position Mode: net_mode (SPOT)")
            elif account_config.get("posMode") == "long_short_mode":
                print("❌ Position Mode: long_short_mode (MARGIN)")
            else:
                print(f"⚠️ Position Mode: {account_config.get('posMode')} (Unknown)")

            # Проверяем займы
            if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
                print("❌ Есть займы - блокирует торговлю")
            else:
                print("✅ Займов нет")

            # 5. Рекомендации
            print("\n5️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)

            if account_config.get("posMode") == "long_short_mode":
                print("🔧 ПРОБЛЕМА: Position Mode = long_short_mode")
                print("   РЕШЕНИЕ: Переключить на net_mode в OKX")
                print("   Settings → Trading → Position Mode → Net")

            if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
                print("🔧 ПРОБЛЕМА: Есть займы")
                print("   РЕШЕНИЕ: Погасить займы в OKX")
                print("   Portfolio → Borrow → Repay All")

            # 6. Проверяем логику бота
            print("\n6️⃣ ЛОГИКА БОТА:")
            print("-" * 30)
            print("   Бот проверяет займы перед каждой сделкой")
            print("   Если есть займы - блокирует торговлю")
            print("   Это правильная логика для SPOT торговли")

            # 7. Тест размещения ордера
            print("\n7️⃣ ТЕСТ РАЗМЕЩЕНИЯ ОРДЕРА:")
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

            except Exception as e:
                print(f"❌ Ошибка размещения ордера: {e}")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(check_trading_mode_detailed())
