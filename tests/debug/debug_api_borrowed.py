import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
Диагностика API займов
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def debug_api_borrowed():
    """Диагностика API займов"""
    print("🔍 ДИАГНОСТИКА API ЗАЙМОВ")
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

            # 2. Проверяем баланс напрямую через API
            print("\n2️⃣ ПРЯМОЙ ЗАПРОС БАЛАНСА:")
            print("-" * 30)
            try:
                balance_response = await client._make_request("GET", "/account/balance")
                print(f"   Полный ответ API: {balance_response}")

                # Ищем займы в ответе
                if balance_response.get("data"):
                    for account in balance_response["data"]:
                        for detail in account.get("details", []):
                            if detail.get("ccy") in ["BTC", "USDT"]:
                                print(f"   {detail.get('ccy')}:")
                                print(f"     Balance: {detail.get('bal', '0')}")
                                print(f"     Available: {detail.get('availBal', '0')}")
                                print(f"     Borrowed: {detail.get('borrowed', '0')}")
                                print(f"     Interest: {detail.get('interest', '0')}")

            except Exception as e:
                print(f"   Ошибка прямого запроса: {e}")

            # 3. Проверяем метод get_borrowed_balance
            print("\n3️⃣ МЕТОД get_borrowed_balance:")
            print("-" * 30)
            try:
                btc_borrowed = await client.get_borrowed_balance("BTC")
                usdt_borrowed = await client.get_borrowed_balance("USDT")
                print(f"   BTC займ (метод): {btc_borrowed}")
                print(f"   USDT займ (метод): {usdt_borrowed}")
            except Exception as e:
                print(f"   Ошибка метода: {e}")

            # 4. Анализ проблемы
            print("\n4️⃣ АНАЛИЗ ПРОБЛЕМЫ:")
            print("-" * 30)

            if account_config.get("posMode") == "long_short_mode":
                print("❌ ПРОБЛЕМА: Position Mode = long_short_mode")
                print("   Это MARGIN режим, поэтому API возвращает займы")
                print("   РЕШЕНИЕ: Переключить на net_mode в OKX")
            else:
                print("✅ Position Mode: SPOT")

            # 5. Проверяем логику бота
            print("\n5️⃣ ЛОГИКА БОТА:")
            print("-" * 30)
            print("   Бот проверяет: borrowed_base > 0 or borrowed_quote > 0")
            print("   Если есть займы - блокирует торговлю")
            print("   Это правильная логика для SPOT торговли")

            # 6. Рекомендации
            print("\n6️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)
            print("1. Переключить Position Mode на Net в OKX")
            print("2. Убедиться, что borrowed = 0")
            print("3. Перезапустить бота")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_api_borrowed())
