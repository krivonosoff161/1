"""
ПРЯМОЙ ЗАПРОС К OKX API
Обходим наш клиент и делаем прямые запросы к OKX
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime

import aiohttp


async def direct_okx_api_check():
    """Прямой запрос к OKX API"""
    print("🔧 ПРЯМОЙ ЗАПРОС К OKX API")
    print("=" * 60)

    # Получаем API ключи из переменных окружения
    api_key = os.getenv("OKX_API_KEY")
    api_secret = os.getenv("OKX_API_SECRET")
    passphrase = os.getenv("OKX_PASSPHRASE")

    if not all([api_key, api_secret, passphrase]):
        print("❌ API ключи не найдены в переменных окружения")
        return False

    base_url = "https://www.okx.com"  # Sandbox URL

    async with aiohttp.ClientSession() as session:
        try:
            # 1. ПРОВЕРКА ОТКРЫТЫХ ОРДЕРОВ
            print(f"\n📋 ПРОВЕРКА ОТКРЫТЫХ ОРДЕРОВ:")
            print("-" * 50)

            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            method = "GET"
            request_path = "/api/v5/trade/orders-pending"
            body = ""

            # Генерируем подпись
            message = timestamp + method + request_path + body
            signature = base64.b64encode(
                hmac.new(
                    api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
                ).digest()
            ).decode("utf-8")

            headers = {
                "OK-ACCESS-KEY": api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
                "x-simulated-trading": "1",  # Sandbox
            }

            url = base_url + request_path
            async with session.get(url, headers=headers) as response:
                result = await response.json()
                print(f"📊 Статус: {response.status}")
                print(f"📊 Code: {result.get('code')}")
                print(f"📊 Message: {result.get('msg')}")
                print(f"📊 Data: {result.get('data', [])}")
                print(f"📊 Количество ордеров: {len(result.get('data', []))}")

                for i, order in enumerate(result.get("data", []), 1):
                    print(f"   {i}. ID: {order.get('ordId')}")
                    print(f"      Symbol: {order.get('instId')}")
                    print(f"      Side: {order.get('side')}")
                    print(f"      Type: {order.get('ordType')}")
                    print(f"      Size: {order.get('sz')}")
                    print(f"      Price: {order.get('px')}")
                    print(f"      State: {order.get('state')}")
                    print()

            # 2. ПРОВЕРКА АЛГОРИТМИЧЕСКИХ ОРДЕРОВ
            print(f"\n🤖 ПРОВЕРКА АЛГОРИТМИЧЕСКИХ ОРДЕРОВ:")
            print("-" * 50)

            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            method = "GET"
            request_path = "/api/v5/trade/orders-algo-pending"
            body = ""

            # Генерируем подпись
            message = timestamp + method + request_path + body
            signature = base64.b64encode(
                hmac.new(
                    api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
                ).digest()
            ).decode("utf-8")

            headers = {
                "OK-ACCESS-KEY": api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
                "x-simulated-trading": "1",  # Sandbox
            }

            url = base_url + request_path
            async with session.get(url, headers=headers) as response:
                result = await response.json()
                print(f"📊 Статус: {response.status}")
                print(f"📊 Code: {result.get('code')}")
                print(f"📊 Message: {result.get('msg')}")
                print(f"📊 Data: {result.get('data', [])}")
                print(f"📊 Количество algo ордеров: {len(result.get('data', []))}")

                for i, order in enumerate(result.get("data", []), 1):
                    print(f"   {i}. Algo ID: {order.get('algoId')}")
                    print(f"      Symbol: {order.get('instId')}")
                    print(f"      Type: {order.get('ordType')}")
                    print(f"      Side: {order.get('side')}")
                    print(f"      Size: {order.get('sz')}")
                    print(f"      TP: {order.get('tpTriggerPx')}")
                    print(f"      SL: {order.get('slTriggerPx')}")
                    print(f"      State: {order.get('state')}")
                    print()

            # 3. ПРОВЕРКА ПОЗИЦИЙ
            print(f"\n💼 ПРОВЕРКА ПОЗИЦИЙ:")
            print("-" * 50)

            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            method = "GET"
            request_path = "/api/v5/account/positions"
            body = ""

            # Генерируем подпись
            message = timestamp + method + request_path + body
            signature = base64.b64encode(
                hmac.new(
                    api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
                ).digest()
            ).decode("utf-8")

            headers = {
                "OK-ACCESS-KEY": api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
                "x-simulated-trading": "1",  # Sandbox
            }

            url = base_url + request_path
            async with session.get(url, headers=headers) as response:
                result = await response.json()
                print(f"📊 Статус: {response.status}")
                print(f"📊 Code: {result.get('code')}")
                print(f"📊 Message: {result.get('msg')}")
                print(f"📊 Data: {result.get('data', [])}")
                print(f"📊 Количество позиций: {len(result.get('data', []))}")

                for i, pos in enumerate(result.get("data", []), 1):
                    print(f"   {i}. Symbol: {pos.get('instId')}")
                    print(f"      Side: {pos.get('posSide')}")
                    print(f"      Size: {pos.get('pos')}")
                    print(f"      Avg Price: {pos.get('avgPx')}")
                    print(f"      Unrealized PnL: {pos.get('upl')}")
                    print()

            # 4. ПРОВЕРКА ИСТОРИИ ОРДЕРОВ
            print(f"\n📜 ПРОВЕРКА ИСТОРИИ ОРДЕРОВ:")
            print("-" * 50)

            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            method = "GET"
            request_path = "/api/v5/trade/orders-history?instId=ETH-USDT&limit=20"
            body = ""

            # Генерируем подпись
            message = timestamp + method + request_path + body
            signature = base64.b64encode(
                hmac.new(
                    api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
                ).digest()
            ).decode("utf-8")

            headers = {
                "OK-ACCESS-KEY": api_key,
                "OK-ACCESS-SIGN": signature,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
                "x-simulated-trading": "1",  # Sandbox
            }

            url = base_url + request_path
            async with session.get(url, headers=headers) as response:
                result = await response.json()
                print(f"📊 Статус: {response.status}")
                print(f"📊 Code: {result.get('code')}")
                print(f"📊 Message: {result.get('msg')}")
                print(f"📊 Data: {result.get('data', [])}")
                print(f"📊 Количество ордеров в истории: {len(result.get('data', []))}")

                for i, order in enumerate(
                    result.get("data", [])[:10], 1
                ):  # Показываем первые 10
                    print(f"   {i}. ID: {order.get('ordId')}")
                    print(f"      Symbol: {order.get('instId')}")
                    print(f"      Side: {order.get('side')}")
                    print(f"      Type: {order.get('ordType')}")
                    print(f"      Size: {order.get('sz')}")
                    print(f"      Price: {order.get('px')}")
                    print(f"      State: {order.get('state')}")
                    print(f"      Fill Size: {order.get('fillSz')}")
                    print(f"      Fill Price: {order.get('fillPx')}")
                    print()

            print("✅ Прямой API запрос завершен")
            return True

        except Exception as e:
            print(f"❌ Ошибка прямого API запроса: {e}")
            return False


if __name__ == "__main__":
    asyncio.run(direct_okx_api_check())
