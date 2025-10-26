"""
Тест WebSocket Order Executor для быстрых входов
Проверяет латентность и функциональность
"""

import asyncio
import sys
from datetime import datetime

from loguru import logger

# Добавляем корневую директорию проекта в sys.path
sys.path.append(".")

from src.config import load_config
from src.models import OrderSide
from src.okx_client import OKXClient
from src.websocket_order_executor import WebSocketOrderExecutor


async def test_websocket_latency():
    """Тест латентности WebSocket vs REST"""
    print("🔍 ТЕСТ ЛАТЕНТНОСТИ WEBSOCKET vs REST")
    print("=" * 50)

    try:
        config = load_config()
        client = OKXClient(config.api["okx"])
        await client.connect()

        # Тест REST латентности
        print("📊 Измерение REST API латентности...")
        start_time = datetime.utcnow()
        ticker = await client.get_ticker("BTC-USDT")
        rest_latency = (datetime.utcnow() - start_time).total_seconds() * 1000
        print(f"   REST API: {rest_latency:.1f} мс")

        # Тест WebSocket латентности
        print("📊 Измерение WebSocket латентности...")
        ws_executor = WebSocketOrderExecutor(config.api["okx"])
        if await ws_executor.connect():
            ws_latency = await ws_executor.get_latency()
            print(f"   WebSocket: {ws_latency:.1f} мс")

            # Сравнение
            improvement = rest_latency - ws_latency
            improvement_percent = (improvement / rest_latency) * 100
            print(f"   Улучшение: {improvement:.1f} мс ({improvement_percent:.1f}%)")

            await ws_executor.disconnect()
        else:
            print("   ❌ WebSocket не подключился")

        await client.disconnect()

    except Exception as e:
        print(f"❌ Ошибка теста: {e}")


async def test_websocket_order():
    """Тест размещения ордера через WebSocket"""
    print("\n🚀 ТЕСТ WEBSOCKET ОРДЕРА")
    print("=" * 50)

    try:
        config = load_config()
        ws_executor = WebSocketOrderExecutor(config.api["okx"])

        if await ws_executor.connect():
            print("✅ WebSocket подключен")

            # Тест размещения ордера (демо)
            print("📤 Тест размещения ордера...")
            print("   ⚠️ ВНИМАНИЕ: Это тест на САНДБОКСЕ!")

            # Получаем текущую цену
            client = OKXClient(config.api["okx"])
            await client.connect()
            ticker = await client.get_ticker("BTC-USDT")
            current_price = float(ticker.get("last", 0))
            print(f"   Текущая цена BTC: ${current_price:.2f}")

            # Тест ордера (очень маленький размер)
            test_quantity = 0.0001  # $10 при цене $100k
            print(f"   Тестовый размер: {test_quantity} BTC")

            # Размещаем тестовый ордер
            start_time = datetime.utcnow()
            order = await ws_executor.place_market_order(
                symbol="BTC-USDT",
                side=OrderSide.BUY,
                quantity=test_quantity,
                price=current_price,
            )
            order_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            if order:
                print(f"   ✅ Ордер размещен за {order_time:.1f} мс")
                print(f"   Order ID: {order.id}")
                print(f"   Status: {order.status}")
            else:
                print(f"   ❌ Ордер не размещен за {order_time:.1f} мс")

            await ws_executor.disconnect()
            await client.disconnect()

        else:
            print("❌ WebSocket не подключился")

    except Exception as e:
        print(f"❌ Ошибка теста ордера: {e}")


async def main():
    """Главная функция тестирования"""
    print("🧪 ТЕСТИРОВАНИЕ WEBSOCKET ORDER EXECUTOR")
    print("=" * 60)

    # Тест 1: Латентность
    await test_websocket_latency()

    # Тест 2: Размещение ордера
    await test_websocket_order()

    print("\n✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
