#!/usr/bin/env python3
"""
Детальная диагностика Batch API
"""
import asyncio
import sys

sys.path.append(".")
from src.config import load_config
from src.okx_client import OKXClient


async def debug_batch_detailed():
    """Детальная диагностика Batch API"""
    print("🔍 ДЕТАЛЬНАЯ ДИАГНОСТИКА BATCH API")
    print("=" * 60)

    try:
        config = load_config()
        async with OKXClient(config.api["okx"]) as client:
            # 1. Проверяем настройки API
            print("\n1️⃣ НАСТРОЙКИ API:")
            print("-" * 30)
            print(f"   API Key: {client.api_key[:10]}...")
            print(f"   Secret: {client.api_secret[:10]}...")
            print(f"   Passphrase: {client.passphrase}")
            print(f"   Base URL: {client.base_url}")
            print(f"   Sandbox: {client.sandbox}")

            # 2. Тест простого запроса
            print("\n2️⃣ ТЕСТ ПРОСТОГО ЗАПРОСА:")
            print("-" * 30)
            try:
                account_config = await client.get_account_config()
                print("✅ Простой запрос работает")
                print(f"   Account Level: {account_config.get('acctLv')}")
                print(f"   Position Mode: {account_config.get('posMode')}")
            except Exception as e:
                print(f"❌ Простой запрос не работает: {e}")
                return

            # 3. Тест размещения ордера
            print("\n3️⃣ ТЕСТ РАЗМЕЩЕНИЯ ОРДЕРА:")
            print("-" * 30)
            try:
                test_order = await client.place_order(
                    inst_id="BTC-USDT",
                    side="buy",
                    order_type="LIMIT",
                    quantity="0.0001",
                    price="50000",
                    post_only=True,
                )
                if test_order.get("data"):
                    order_id = test_order["data"][0]["ordId"]
                    print(f"✅ Тестовый ордер размещен: {order_id}")

                    # Отменяем ордер
                    await client.cancel_order("BTC-USDT", order_id)
                    print("✅ Тестовый ордер отменен")
                else:
                    print("❌ Тестовый ордер не размещен")
            except Exception as e:
                print(f"❌ Ошибка размещения ордера: {e}")
                return

            # 4. Тест batch amend с правильными параметрами
            print("\n4️⃣ ТЕСТ BATCH AMEND:")
            print("-" * 30)
            try:
                # Создаем тестовый ордер для изменения
                test_order = await client.place_order(
                    inst_id="BTC-USDT",
                    side="buy",
                    order_type="LIMIT",
                    quantity="0.0001",
                    price="50000",
                    post_only=True,
                )

                if test_order.get("data"):
                    order_id = test_order["data"][0]["ordId"]
                    print(f"   Создан тестовый ордер: {order_id}")

                    # Тест batch amend
                    test_batch = [
                        {"instId": "BTC-USDT", "ordId": order_id, "newPx": "51000"}
                    ]

                    print(f"   Отправляем batch amend...")
                    result = await client.batch_amend_orders(test_batch)
                    print(f"   Batch result: {result}")

                    # Отменяем тестовый ордер
                    await client.cancel_order("BTC-USDT", order_id)
                    print("✅ Тестовый ордер отменен")

                else:
                    print("❌ Не удалось создать тестовый ордер")

            except Exception as e:
                print(f"❌ Batch amend ошибка: {e}")
                print(f"   Тип ошибки: {type(e).__name__}")

                # Анализируем ошибку
                if "APIKey does not match current environment" in str(e):
                    print("\n🔍 АНАЛИЗ ОШИБКИ:")
                    print("   Проблема: API ключ не подходит для среды")
                    print("   Возможные причины:")
                    print("   1. API ключ для live, а запрос на sandbox")
                    print("   2. API ключ для sandbox, а запрос на live")
                    print("   3. Неправильная настройка sandbox режима")

                    # Проверяем заголовки
                    print("\n🔍 ПРОВЕРКА ЗАГОЛОВКОВ:")
                    print(f"   x-simulated-trading: 1 (sandbox)")
                    print(f"   Base URL: {client.base_url}")
                    print(f"   Sandbox: {client.sandbox}")

                    if client.sandbox:
                        print("   ✅ Sandbox режим включен")
                        print("   ❌ ПРОБЛЕМА: API ключ не для sandbox")
                    else:
                        print("   ❌ Sandbox режим выключен")
                        print("   ❌ ПРОБЛЕМА: Нужен sandbox API ключ")

            # 5. Рекомендации
            print("\n5️⃣ РЕКОМЕНДАЦИИ:")
            print("-" * 30)
            print("1. Проверить, что API ключ создан для sandbox")
            print("2. Убедиться, что sandbox: true в config.yaml")
            print("3. Проверить заголовки запросов")
            print("4. Возможно, отключить batch amend для демо")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_batch_detailed())
