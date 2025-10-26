import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

"""
ЭКСТРЕННАЯ ПРОВЕРКА ВСЕХ СОСТОЯНИЙ ОРДЕРОВ
Проверяем все возможные состояния и типы
"""

import asyncio
import base64
import hashlib
import hmac
import sys
from datetime import datetime

import aiohttp

sys.path.append(".")

from src.config import load_config
from src.main import BotRunner


async def emergency_check_all_states():
    """Экстренная проверка всех состояний ордеров"""
    print("🚨 ЭКСТРЕННАЯ ПРОВЕРКА ВСЕХ СОСТОЯНИЙ ОРДЕРОВ")
    print("=" * 70)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ПРОВЕРКА ВСЕХ СОСТОЯНИЙ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ
        print(f"\n🤖 ВСЕ СОСТОЯНИЯ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ:")
        print("-" * 60)

        states = ["live", "effective", "partially_filled", "filled", "cancelled", "all"]

        for state in states:
            try:
                print(f"\n📊 Проверяем состояние: {state}")

                # Прямой запрос с разными состояниями
                timestamp = (
                    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                )
                request_path = f"/trade/orders-algo-pending?instType=SPOT&state={state}"

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
                        print(f"   Статус: {response.status}")
                        print(f"   Code: {result.get('code')}")
                        print(f"   Message: {result.get('msg')}")
                        print(f"   Количество: {len(result.get('data', []))}")

                        if result.get("data"):
                            for order in result.get("data", []):
                                print(f"      {order}")
                        print()

            except Exception as e:
                print(f"   ❌ Ошибка для {state}: {e}")

        # 2. ПРОВЕРКА ВСЕХ ТИПОВ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ
        print(f"\n🤖 ВСЕ ТИПЫ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ:")
        print("-" * 60)

        ord_types = [
            "oco",
            "conditional",
            "trigger",
            "move_order_stop",
            "iceberg",
            "twap",
        ]

        for ord_type in ord_types:
            try:
                print(f"\n📊 Проверяем тип: {ord_type}")

                # Прямой запрос с разными типами
                timestamp = (
                    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                )
                request_path = (
                    f"/trade/orders-algo-pending?instType=SPOT&ordType={ord_type}"
                )

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
                        print(f"   Статус: {response.status}")
                        print(f"   Code: {result.get('code')}")
                        print(f"   Message: {result.get('msg')}")
                        print(f"   Количество: {len(result.get('data', []))}")

                        if result.get("data"):
                            for order in result.get("data", []):
                                print(f"      {order}")
                        print()

            except Exception as e:
                print(f"   ❌ Ошибка для {ord_type}: {e}")

        # 3. ПРОВЕРКА ОБЫЧНЫХ ОРДЕРОВ С РАЗНЫМИ СОСТОЯНИЯМИ
        print(f"\n📋 ОБЫЧНЫЕ ОРДЕРА С РАЗНЫМИ СОСТОЯНИЯМИ:")
        print("-" * 60)

        order_states = ["live", "partially_filled", "filled", "cancelled", "all"]

        for state in order_states:
            try:
                print(f"\n📊 Проверяем состояние: {state}")

                # Прямой запрос обычных ордеров
                timestamp = (
                    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                )
                request_path = f"/trade/orders-pending?instType=SPOT&state={state}"

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
                        print(f"   Статус: {response.status}")
                        print(f"   Code: {result.get('code')}")
                        print(f"   Message: {result.get('msg')}")
                        print(f"   Количество: {len(result.get('data', []))}")

                        if result.get("data"):
                            for order in result.get("data", []):
                                print(f"      {order}")
                        print()

            except Exception as e:
                print(f"   ❌ Ошибка для {state}: {e}")

        await bot.shutdown()
        print("\n✅ Экстренная проверка завершена")

        return True

    except Exception as e:
        print(f"❌ Ошибка экстренной проверки: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(emergency_check_all_states())
