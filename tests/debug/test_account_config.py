#!/usr/bin/env python3
"""
Тест для диагностики Account Config "Invalid Sign" ошибки
"""

import asyncio
import os
import sys
from pathlib import Path

# Устанавливаем UTF-8 для консоли
if sys.platform == "win32":
    os.system("chcp 65001 >nul")

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.okx_client import OKXClient


async def test_account_config():
    """Тест Account Config функциональности"""

    print("=" * 60)
    print("🔧 ТЕСТ: ACCOUNT CONFIG")
    print("=" * 60)

    # Загружаем конфигурацию
    config = load_config()
    api_config = list(config.api.values())[0]
    client = OKXClient(api_config)
    await client.connect()

    try:
        print(f"\n🔍 Шаг 1: Проверяем настройки аккаунта...")

        try:
            result = await client.check_account_mode()
            print(f"✅ Account config успешен!")
            print(f"   Результат: {result}")

        except Exception as e:
            print(f"❌ Account config failed: {e}")

            # Детальная диагностика
            print(f"\n🔍 ДИАГНОСТИКА:")
            print(f"   Ошибка: {type(e).__name__}: {e}")

            # Проверяем, что именно происходит
            print(f"\n📊 Проверяем другие endpoints...")

            try:
                # Тестируем простой endpoint
                balance = await client.get_account_balance()
                print(f"   ✅ get_account_balance работает: {len(balance)} активов")
            except Exception as e2:
                print(f"   ❌ get_account_balance failed: {e2}")

            try:
                # Тестируем другой endpoint
                price = await client.get_current_price("ETH-USDT")
                print(f"   ✅ get_current_price работает: ${price:.2f}")
            except Exception as e3:
                print(f"   ❌ get_current_price failed: {e3}")

        print(f"\n✅ Тест завершен")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test_account_config())
