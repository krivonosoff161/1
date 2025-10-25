#!/usr/bin/env python3
"""
Диагностика проблемы с балансом и займами
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def diagnose_balance_issue():
    """Диагностика проблемы с балансом"""
    print("🔍 ДИАГНОСТИКА ПРОБЛЕМЫ С БАЛАНСОМ")
    print("=" * 60)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем режим торговли
            print("\n1️⃣ РЕЖИМ ТОРГОВЛИ:")
            print("-" * 30)
            account_config = await client.get_account_config()
            print(f"   Account Level: {account_config.get('acctLv', 'N/A')}")
            print(f"   Trading Mode: {account_config.get('posMode', 'N/A')}")
            print(f"   Auto Loan: {account_config.get('autoLoan', 'N/A')}")

            # 2. Проверяем баланс
            print("\n2️⃣ БАЛАНС:")
            print("-" * 30)
            balance = await client.get_balance("USDT")
            print(f"   USDT Balance: {balance}")

            # Получаем полную информацию о балансе
            try:
                balance_all = await client.get_balance_all()
                print(f"   Полный баланс: {balance_all}")
            except AttributeError:
                print("   Полный баланс: метод не найден")

            # 3. Проверяем займы
            print("\n3️⃣ ЗАЙМЫ:")
            print("-" * 30)
            btc_borrowed = await client.get_borrowed_balance("BTC")
            usdt_borrowed = await client.get_borrowed_balance("USDT")
            print(f"   BTC займ: {btc_borrowed}")
            print(f"   USDT займ: {usdt_borrowed}")

            # 4. Проверяем недавние ордера
            print("\n4️⃣ НЕДАВНИЕ ОРДЕРА:")
            print("-" * 30)
            orders = await client.get_order_history_all()
            recent_orders = orders.get("data", [])[:3]
            for order in recent_orders:
                print(
                    f"   {order.get('ordId')}: {order.get('side')} {order.get('sz')} {order.get('instId')} - {order.get('state')}"
                )

            # 5. Анализ проблемы
            print("\n5️⃣ АНАЛИЗ ПРОБЛЕМЫ:")
            print("-" * 30)

            if account_config.get("posMode") == "long_short_mode":
                print("❌ ПРОБЛЕМА: Trading Mode = long_short_mode (MARGIN)")
                print("   РЕШЕНИЕ: Переключить на SPOT режим в OKX")
                print("   Settings → Trading → Position Mode → Net")
            else:
                print("✅ Trading Mode: SPOT")

            if account_config.get("autoLoan") == "true":
                print("❌ ПРОБЛЕМА: Auto Loan = true")
                print("   РЕШЕНИЕ: Отключить Auto Loan в OKX")
                print("   Settings → Auto Loan → OFF")
            else:
                print("✅ Auto Loan: OFF")

            if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
                print("❌ ПРОБЛЕМА: Есть займы")
                print("   РЕШЕНИЕ: Погасить займы в OKX")
                print("   Portfolio → Borrow → Repay All")
            else:
                print("✅ Займов нет")

            # 6. Рекомендации
            print("\n6️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)
            print("1. Откройте OKX в браузере")
            print("2. Settings → Trading → Position Mode → Net")
            print("3. Settings → Auto Loan → OFF")
            print("4. Portfolio → Borrow → Repay All")
            print("5. Убедитесь, что borrowed = 0")
            print("6. Перезапустите бота")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(diagnose_balance_issue())
