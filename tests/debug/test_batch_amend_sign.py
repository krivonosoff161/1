#!/usr/bin/env python3
"""
Debug-TEST: Batch-amend signature (Error 50113)
Запуск: python tests/debug/test_batch_amend_sign.py
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import load_config
from src.okx_client import OKXClient


async def main():
    print("=" * 60)
    print("🔧 ТЕСТ: BATCH AMEND SIGNATURE")
    print("=" * 60)

    # Загружаем конфигурацию
    config = load_config()
    api_config = list(config.api.values())[0]
    client = OKXClient(api_config)
    await client.connect()

    try:
        # 1. Размещаем 2 рыночных ордера (для batch-amend)
        symbol = "ETH-USDT"
        orders = []

        print(f"\n🛒 Шаг 1: Создаем тестовые ордера...")

        for i in range(2):
            res = await client.place_order(
                symbol=symbol, side="buy", order_type="market", quantity=0.001
            )
            if hasattr(res, "id") and res.id:
                orders.append(res.id)
                print(f"   ✅ Ордер {i+1}: {res.id}")
            else:
                print(f"   ❌ Ошибка создания ордера {i+1}: {res}")

        if not orders:
            print("❌ Не удалось создать ордера для тестирования")
            return

        print(f"✅ Созданы ордера: {orders}")

        # 2. Формируем batch-amend payload
        print(f"\n🔧 Шаг 2: Формируем batch-amend payload...")

        amend_payload = [
            {"instId": symbol, "ordId": oid, "newPx": "2000"}  # новая цена (любая)
            for oid in orders
        ]

        print(f"   Payload: {amend_payload}")

        # 3. Пробуем batch-amend
        print(f"\n🚀 Шаг 3: Тестируем batch-amend...")

        try:
            resp = await client.batch_amend_orders(amend_payload)
            print("✅ Batch-amend успешно:", resp)
        except Exception as e:
            print("❌ Batch-amend ошибка:", e)

            # Детальная диагностика
            print(f"\n🔍 ДИАГНОСТИКА:")
            print(f"   Ордера: {orders}")
            print(f"   Payload: {amend_payload}")
            print(f"   Ошибка: {type(e).__name__}: {e}")

        # 4. Отменяем тестовые ордера
        print(f"\n🧹 Шаг 4: Очистка...")

        for oid in orders:
            try:
                await client.cancel_order(symbol, oid)
                print(f"   ✅ Ордер {oid} отменен")
            except Exception as e:
                print(f"   ❌ Ошибка отмены ордера {oid}: {e}")

        print("🧹 Тестовые ордера отменены")

    finally:
        await client.disconnect()
        print(f"\n✅ Тест завершен")


if __name__ == "__main__":
    asyncio.run(main())
