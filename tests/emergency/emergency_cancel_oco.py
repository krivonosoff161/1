import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

"""
ЭКСТРЕННАЯ ОТМЕНА OCO ОРДЕРОВ
Отменяем OCO ордера вручную через прямой API запрос
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


async def emergency_cancel_oco():
    """Экстренная отмена OCO ордеров"""
    print("🚨 ЭКСТРЕННАЯ ОТМЕНА OCO ОРДЕРОВ")
    print("=" * 60)

    try:
        config = load_config()
        bot = BotRunner(config, mode="rest")
        await bot.initialize()

        print("✅ Бот подключен к бирже")

        # 1. ПОПЫТКА ОТМЕНЫ ВСЕХ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ
        print(f"\n🚨 ОТМЕНА ВСЕХ АЛГОРИТМИЧЕСКИХ ОРДЕРОВ:")
        print("-" * 50)

        try:
            # Прямой запрос на отмену всех algo ордеров
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            request_path = "/trade/cancel-algos"

            # Данные для отмены всех algo ордеров
            data = {"instType": "SPOT", "instId": "ETH-USDT"}

            body = str(data).replace("'", '"')
            message = timestamp + "POST" + request_path + body

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
                async with session.post(url, headers=headers, data=body) as response:
                    result = await response.json()
                    print(f"📊 Статус: {response.status}")
                    print(f"📊 Code: {result.get('code')}")
                    print(f"📊 Message: {result.get('msg')}")
                    print(f"📊 Data: {result.get('data', [])}")

        except Exception as e:
            print(f"❌ Ошибка отмены algo ордеров: {e}")

        # 2. ПОПЫТКА ОТМЕНЫ ВСЕХ ОБЫЧНЫХ ОРДЕРОВ
        print(f"\n🚨 ОТМЕНА ВСЕХ ОБЫЧНЫХ ОРДЕРОВ:")
        print("-" * 50)

        try:
            # Прямой запрос на отмену всех обычных ордеров
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            request_path = "/trade/cancel-orders"

            # Данные для отмены всех ордеров
            data = {"instType": "SPOT", "instId": "ETH-USDT"}

            body = str(data).replace("'", '"')
            message = timestamp + "POST" + request_path + body

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
                async with session.post(url, headers=headers, data=body) as response:
                    result = await response.json()
                    print(f"📊 Статус: {response.status}")
                    print(f"📊 Code: {result.get('code')}")
                    print(f"📊 Message: {result.get('msg')}")
                    print(f"📊 Data: {result.get('data', [])}")

        except Exception as e:
            print(f"❌ Ошибка отмены обычных ордеров: {e}")

        # 3. ПРОВЕРКА РЕЗУЛЬТАТА
        print(f"\n🔍 ПРОВЕРКА РЕЗУЛЬТАТА:")
        print("-" * 50)

        try:
            # Проверяем через наш клиент
            open_orders = await bot.client.get_open_orders()
            algo_orders = await bot.client.get_algo_orders()

            print(f"📊 Открытых ордеров: {len(open_orders)}")
            print(f"📊 Алгоритмических ордеров: {len(algo_orders)}")

            if len(open_orders) == 0 and len(algo_orders) == 0:
                print("✅ Все ордера отменены!")
            else:
                print("❌ Ордера все еще открыты!")

        except Exception as e:
            print(f"❌ Ошибка проверки: {e}")

        await bot.shutdown()
        print("\n✅ Экстренная отмена завершена")

        return True

    except Exception as e:
        print(f"❌ Ошибка экстренной отмены: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(emergency_cancel_oco())
