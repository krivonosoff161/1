#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка структуры fills от биржи - что именно приходит
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.clients.futures_client import OKXFuturesClient
from src.config import load_config


async def main():
    """Проверяем структуру fills"""
    print("=" * 80)
    print("🔍 ПРОВЕРКА СТРУКТУРЫ FILLS ОТ БИРЖИ")
    print("=" * 80)

    config = load_config("config.yaml")
    api_config = config.get_okx_config()

    client = OKXFuturesClient(
        api_key=api_config.api_key,
        secret_key=api_config.api_secret,
        passphrase=api_config.passphrase,
        sandbox=api_config.sandbox,
    )

    # Получаем последние fills
    end_time = datetime.now()
    start_time = end_time - timedelta(days=1)

    params = {
        "instType": "SWAP",
        "limit": "5",  # Только 5 для примера
        "begin": str(int(start_time.timestamp() * 1000)),
        "end": str(int(end_time.timestamp() * 1000)),
    }

    try:
        response = await client._make_request(
            "GET", "/api/v5/trade/fills", params=params
        )

        print("\n📊 Сырой ответ от биржи:")
        print(json.dumps(response, indent=2, ensure_ascii=False))

        if response.get("code") == "0" and response.get("data"):
            fills = response["data"]
            print(f"\n✅ Получено {len(fills)} fills")

            if fills:
                print("\n📋 Структура первого fill:")
                first_fill = fills[0]
                for key, value in first_fill.items():
                    print(f"   {key}: {value} (тип: {type(value).__name__})")

                # Проверяем наличие PnL полей
                print("\n🔍 Поиск полей связанных с PnL:")
                pnl_keys = [
                    k
                    for k in first_fill.keys()
                    if "pnl" in k.lower() or "pnl" in str(k).lower()
                ]
                if pnl_keys:
                    print(f"   Найдены поля: {pnl_keys}")
                    for key in pnl_keys:
                        print(f"   {key}: {first_fill.get(key)}")
                else:
                    print("   ❌ Поля с PnL не найдены в fills")

    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await client.close()

    print("\n" + "=" * 80)
    print("✅ ПРОВЕРКА ЗАВЕРШЕНА")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
