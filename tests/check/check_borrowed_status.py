import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
Проверка статуса займов на OKX
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def check_borrowed():
    config = load_config()
    async with OKXClient(config.api["okx"]) as client:
        # Проверяем займы
        btc_borrowed = await client.get_borrowed_balance("BTC")
        usdt_borrowed = await client.get_borrowed_balance("USDT")

        print("🔍 ТЕКУЩИЙ СТАТУС ЗАЙМОВ:")
        print(f"   BTC займ: {btc_borrowed}")
        print(f"   USDT займ: {usdt_borrowed}")

        # Проверяем общий баланс
        btc_balance = await client.get_balance("BTC")
        usdt_balance = await client.get_balance("USDT")
        print("\n💰 ОБЩИЙ БАЛАНС:")
        print(
            f'   BTC: {btc_balance.get("bal", "0")} (займ: {btc_balance.get("borrowed", "0")})'
        )
        print(
            f'   USDT: {usdt_balance.get("bal", "0")} (займ: {usdt_balance.get("borrowed", "0")})'
        )

        # Рекомендации
        if float(btc_borrowed) > 0 or float(usdt_borrowed) > 0:
            print("\n🚨 ДЕЙСТВИЯ ТРЕБУЮТСЯ:")
            print("   1. Откройте OKX в браузере")
            print("   2. Portfolio → Borrow → Repay All")
            print("   3. Убедитесь, что borrowed = 0")
            print("   4. Перезапустите бота")
        else:
            print("\n✅ ЗАЙМОВ НЕТ - БОТ ГОТОВ К ЗАПУСКУ!")


if __name__ == "__main__":
    asyncio.run(check_borrowed())
