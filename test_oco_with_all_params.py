"""
ТЕСТ OCO С ВСЕМИ ПАРАМЕТРАМИ
Проверяем разные комбинации параметров
"""

import asyncio
import sys

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def test_oco_with_all_params():
    """Тест OCO с разными параметрами"""
    print("🔧 ТЕСТ OCO С ВСЕМИ ПАРАМЕТРАМИ")
    print("=" * 60)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ТЕСТ С ПАРАМЕТРОМ STATE=LIVE
        print(f"\n🤖 С ПАРАМЕТРОМ STATE=LIVE:")
        print("-" * 50)

        try:
            oco_orders = await bot.client.get_algo_orders(algo_type="oco")
            print(f"📊 OCO с state=live: {len(oco_orders)}")
            for order in oco_orders:
                print(f"   {order}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

        # 2. ТЕСТ БЕЗ ПАРАМЕТРА STATE
        print(f"\n🤖 БЕЗ ПАРАМЕТРА STATE:")
        print("-" * 50)

        try:
            # Временно убираем параметр state
            import json
            from datetime import datetime

            import aiohttp

            # Прямой запрос без state
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            request_path = "/trade/orders-algo-pending?instType=SPOT&ordType=oco"

            # Генерируем подпись
            message = timestamp + "GET" + request_path + ""
            import base64
            import hashlib
            import hmac

            signature = base64.b64encode(
                hmac.new(
                    bot.client.api_secret.encode("utf-8"),
                    message.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")

            headers = {
                "OK-ACCESS-KEY": bot.client.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": bot.client.passphrase,
                "Content-Type": "application/json",
            }

            if bot.client.sandbox:
                headers["x-simulated-trading"] = "1"

            url = f"{bot.client.base_url}/api/v5{request_path}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    result = await response.json()
                    print(f"📊 Прямой запрос OCO: {len(result.get('data', []))}")
                    print(f"📊 Результат: {result}")
                    for order in result.get("data", []):
                        print(f"   {order}")

        except Exception as e:
            print(f"❌ Ошибка прямого запроса: {e}")

        # 3. ТЕСТ С ПАРАМЕТРОМ STATE=ALL
        print(f"\n🤖 С ПАРАМЕТРОМ STATE=ALL:")
        print("-" * 50)

        try:
            # Прямой запрос с state=all
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            request_path = (
                "/trade/orders-algo-pending?instType=SPOT&ordType=oco&state=all"
            )

            # 🔧 КРИТИЧНО: Используем ПРАВИЛЬНУЮ переменную message!
            message = timestamp + "GET" + request_path + ""

            signature = base64.b64encode(
                hmac.new(
                    bot.client.api_secret.encode("utf-8"),
                    message.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")

            headers = {
                "OK-ACCESS-KEY": bot.client.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": bot.client.passphrase,
                "Content-Type": "application/json",
            }

            if bot.client.sandbox:
                headers["x-simulated-trading"] = "1"

            url = f"{bot.client.base_url}/api/v5{request_path}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    result = await response.json()
                    print(
                        f"📊 Прямой запрос OCO с state=all: {len(result.get('data', []))}"
                    )
                    print(f"📊 Результат: {result}")
                    for order in result.get("data", []):
                        print(f"   {order}")

        except Exception as e:
            print(f"❌ Ошибка прямого запроса с state=all: {e}")

        # 4. ТЕСТ БЕЗ ПАРАМЕТРА ORDTYPE
        print(f"\n🤖 БЕЗ ПАРАМЕТРА ORDTYPE:")
        print("-" * 50)

        try:
            # Прямой запрос без ordType
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            request_path = "/trade/orders-algo-pending?instType=SPOT"

            # 🔧 КРИТИЧНО: Используем ПРАВИЛЬНУЮ переменную message!
            message = timestamp + "GET" + request_path + ""

            signature = base64.b64encode(
                hmac.new(
                    bot.client.api_secret.encode("utf-8"),
                    message.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")

            headers = {
                "OK-ACCESS-KEY": bot.client.api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": bot.client.passphrase,
                "Content-Type": "application/json",
            }

            if bot.client.sandbox:
                headers["x-simulated-trading"] = "1"

            url = f"{bot.client.base_url}/api/v5{request_path}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    result = await response.json()
                    print(f"📊 Прямой запрос без ordType: {len(result.get('data', []))}")
                    print(f"📊 Результат: {result}")
                    for order in result.get("data", []):
                        print(f"   {order}")

        except Exception as e:
            print(f"❌ Ошибка прямого запроса без ordType: {e}")

        await bot.shutdown()
        print("\n✅ Тест завершен")

        return True

    except Exception as e:
        print(f"❌ Ошибка теста: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(test_oco_with_all_params())
