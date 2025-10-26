#!/usr/bin/env python3
"""
Диагностика Batch API
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def debug_batch_api():
    """Диагностика Batch API"""
    print("🔍 ДИАГНОСТИКА BATCH API")
    print("=" * 50)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем API ключ
            print("\n1️⃣ API КЛЮЧ:")
            print("-" * 30)
            print(f"   API Key: {client.api_key[:10]}...")
            print(f"   Secret: {client.api_secret[:10]}...")
            print(f"   Passphrase: {client.passphrase}")

            # 2. Проверяем базовый URL
            print("\n2️⃣ БАЗОВЫЙ URL:")
            print("-" * 30)
            print(f"   Base URL: {client.base_url}")
            print(f"   Sandbox: {client.sandbox}")

            # 3. Тест простого запроса
            print("\n3️⃣ ТЕСТ ПРОСТОГО ЗАПРОСА:")
            print("-" * 30)
            try:
                account_config = await client.get_account_config()
                print("✅ Простой запрос работает")
                print(f"   Account Level: {account_config.get('acctLv')}")
            except Exception as e:
                print(f"❌ Простой запрос не работает: {e}")

            # 4. Тест batch amend
            print("\n4️⃣ ТЕСТ BATCH AMEND:")
            print("-" * 30)
            try:
                # Создаем тестовый batch
                test_batch = [
                    {"instId": "BTC-USDT", "ordId": "test_order_123", "newPx": "50000"}
                ]

                result = await client.batch_amend_orders(test_batch)
                print(f"   Batch result: {result}")
            except Exception as e:
                print(f"❌ Batch amend ошибка: {e}")
                print(f"   Тип ошибки: {type(e).__name__}")

            # 5. Анализ проблемы
            print("\n5️⃣ АНАЛИЗ ПРОБЛЕМЫ:")
            print("-" * 30)

            if "APIKey does not match current environment" in str(e):
                print("❌ ПРОБЛЕМА: API ключ не подходит для среды")
                print("   ВОЗМОЖНЫЕ ПРИЧИНЫ:")
                print("   1. API ключ для sandbox, а запрос на live")
                print("   2. API ключ для live, а запрос на sandbox")
                print("   3. Неправильная настройка sandbox режима")

            # 6. Рекомендации
            print("\n6️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)
            print("1. Проверить настройки sandbox в config.yaml")
            print("2. Убедиться, что API ключ соответствует среде")
            print("3. Проверить заголовки запросов")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_batch_api())
