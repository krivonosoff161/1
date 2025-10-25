#!/usr/bin/env python3
"""
Исправление режима торговли
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def fix_trading_mode():
    """Попытка исправить режим торговли"""
    print("🔧 ИСПРАВЛЕНИЕ РЕЖИМА ТОРГОВЛИ")
    print("=" * 50)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем текущий режим
            print("\n1️⃣ ТЕКУЩИЙ РЕЖИМ:")
            print("-" * 30)
            account_config = await client.get_account_config()
            print(f"   Position Mode: {account_config.get('posMode', 'N/A')}")
            print(f"   Account Level: {account_config.get('acctLv', 'N/A')}")

            # 2. Проверяем займы
            print("\n2️⃣ ЗАЙМЫ:")
            print("-" * 30)
            btc_borrowed = await client.get_borrowed_balance("BTC")
            usdt_borrowed = await client.get_borrowed_balance("USDT")
            print(f"   BTC займ: {btc_borrowed}")
            print(f"   USDT займ: {usdt_borrowed}")

            # 3. Анализ
            print("\n3️⃣ АНАЛИЗ:")
            print("-" * 30)

            if account_config.get("posMode") == "long_short_mode":
                print("❌ ПРОБЛЕМА: Position Mode = long_short_mode (MARGIN)")
                print("   РЕШЕНИЕ: Переключить на net_mode в OKX")
                print("   Settings → Trading → Position Mode → Net")
            else:
                print("✅ Position Mode: SPOT")

            if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
                print("❌ ПРОБЛЕМА: Есть займы")
                print("   РЕШЕНИЕ: Погасить займы в OKX")
            else:
                print("✅ Займов нет")

            # 4. Инструкции
            print("\n4️⃣ ИНСТРУКЦИИ ПО ИСПРАВЛЕНИЮ:")
            print("-" * 30)
            print("1. Откройте OKX в браузере")
            print("2. Перейдите в Settings → Trading")
            print("3. Position Mode → выберите 'Net' (вместо Long/Short)")
            print("4. Сохраните изменения")
            print("5. Убедитесь, что Position Mode = net_mode")

            # 5. Тест после исправления
            print("\n5️⃣ ТЕСТ ПОСЛЕ ИСПРАВЛЕНИЯ:")
            print("-" * 30)
            print("После переключения на Net режим:")
            print("1. Запустите: python test_full_trading_system.py")
            print("2. Проверьте, что бот не блокирует торговлю")
            print("3. Убедитесь, что ордера размещаются успешно")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(fix_trading_mode())
