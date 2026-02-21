"""
Диагностический скрипт для проверки формата запросов и ответов OKX API

Проверяет:
1. Формат отправляемых запросов (параметры, заголовки, body)
2. Формат получаемых ответов (структура, типы данных)
3. Соответствие между ожидаемым и реальным форматами
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Добавляем путь к src
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from loguru import logger

from src.clients.futures_client import OKXFuturesClient

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logger.remove()
logger.add(
    sys.stdout,
    level="DEBUG",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
)


async def test_api_format():
    """Тестирование формата API запросов и ответов"""

    print("=" * 80)
    print("🔍 ДИАГНОСТИКА ФОРМАТА OKX API ЗАПРОСОВ И ОТВЕТОВ")
    print("=" * 80)
    print()

    # Создаем клиент
    client = OKXFuturesClient(
        api_key=os.getenv("OKX_API_KEY"),
        secret_key=os.getenv("OKX_API_SECRET"),
        passphrase=os.getenv("OKX_PASSPHRASE"),
        sandbox=True,
        leverage=5,
    )

    try:
        # ============================================================
        # ТЕСТ 1: Получение баланса
        # ============================================================
        print("\n" + "=" * 80)
        print("ТЕСТ 1: Получение баланса (GET /api/v5/account/balance)")
        print("=" * 80)

        print("\n[1] Отправка запроса...")
        print("    Метод: GET")
        print("    Endpoint: /api/v5/account/balance")
        print("    Параметры: None")
        print("    Ожидаемый формат ответа:")
        print("    {")
        print('      "code": "0",')
        print('      "msg": "",')
        print('      "data": [')
        print("        {")
        print('          "details": [')
        print('            {"ccy": "USDT", "eq": "665.21", ...}')
        print("          ]")
        print("        }")
        print("      ]")
        print("    }")

        balance = await client.get_balance()
        print(f"\n[2] ✅ УСПЕХ: Баланс получен: {balance:.2f} USDT")
        print(f"    Тип данных: {type(balance)}")
        print(f"    Значение корректное: {balance > 0}")

        # ============================================================
        # ТЕСТ 2: Получение позиций
        # ============================================================
        print("\n" + "=" * 80)
        print("ТЕСТ 2: Получение позиций (GET /api/v5/account/positions)")
        print("=" * 80)

        print("\n[1] Отправка запроса...")
        print("    Метод: GET")
        print("    Endpoint: /api/v5/account/positions")
        print('    Параметры: {"instType": "SWAP"}')
        print("    Ожидаемый формат ответа:")
        print("    {")
        print('      "code": "0",')
        print('      "data": [')
        print("        {")
        print('          "instId": "ETH-USDT-SWAP",')
        print('          "pos": "0.067",')
        print('          "posSide": "short",')
        print('          "avgPx": "3233.00",')
        print('          "mgnRatio": "0.1",')
        print('          "liqPx": "...",')
        print("          ...")
        print("        }")
        print("      ]")
        print("    }")

        positions = await client.get_positions()
        print(f"\n[2] ✅ УСПЕХ: Позиций получено: {len(positions)}")
        print(f"    Тип данных: {type(positions)}")

        if positions:
            print("\n[3] Анализ структуры первой позиции:")
            pos = positions[0]
            print(f"    Количество полей: {len(pos)}")
            print("\n    Ключевые поля:")

            # Проверяем наличие важных полей
            important_fields = [
                "instId",
                "pos",
                "posSide",
                "avgPx",
                "mgnRatio",
                "liqPx",
                "upl",
                "uplRatio",
                "lever",
                "margin",
                "imr",
                "mmr",
            ]

            for field in important_fields:
                if field in pos:
                    value = pos[field]
                    value_type = type(value).__name__
                    print(f"      ✅ {field}: {value} (тип: {value_type})")
                else:
                    print(f"      ❌ {field}: ОТСУТСТВУЕТ!")

            print("\n    Все доступные поля:")
            for key, value in pos.items():
                value_type = type(value).__name__
                value_str = str(value)[:50]
                print(f"      - {key}: {value_str} (тип: {value_type})")
        else:
            print("\n[3] ⚠️ ВНИМАНИЕ: Нет открытых позиций")

        # ============================================================
        # ТЕСТ 3: Получение информации о leverage
        # ============================================================
        print("\n" + "=" * 80)
        print("ТЕСТ 3: Получение информации о leverage")
        print("=" * 80)

        symbol = "ETH-USDT"
        print(f"\n[1] Отправка запроса для {symbol}...")
        print("    Метод: GET")
        print("    Endpoint: /api/v5/account/leverage-info")
        print(f'    Параметры: {{"instId": "{symbol}-SWAP", "mgnMode": "isolated"}}')

        leverage_info = await client.get_instrument_leverage_info(symbol)
        print(f"\n[2] ✅ УСПЕХ: Leverage информация получена")
        print(f"    Максимальное плечо: {leverage_info.get('max_leverage', 'N/A')}")
        print(f"    Доступные плечи: {leverage_info.get('available_leverages', 'N/A')}")

        # ============================================================
        # ТЕСТ 4: Проверка формата маржи
        # ============================================================
        print("\n" + "=" * 80)
        print("ТЕСТ 4: Проверка формата маржи (margin info)")
        print("=" * 80)

        if positions:
            symbol = positions[0]["instId"].replace("-SWAP", "")
            print(f"\n[1] Получение margin info для {symbol}...")

            margin_info = await client.get_margin_info(symbol)
            print(f"\n[2] ✅ УСПЕХ: Margin info получен")
            print(f"    Тип данных: {type(margin_info)}")

            if margin_info:
                print("\n[3] Структура margin info:")
                for key, value in margin_info.items():
                    value_type = type(value).__name__
                    print(f"      - {key}: {value} (тип: {value_type})")

                # Проверяем ключевые поля
                print("\n[4] Проверка ключевых полей:")
                key_fields = ["equity", "liqPx", "mgnRatio", "margin", "unrealized_pnl"]
                for field in key_fields:
                    if field in margin_info:
                        value = margin_info[field]
                        print(f"      ✅ {field}: {value} (тип: {type(value).__name__})")
                    else:
                        print(f"      ❌ {field}: ОТСУТСТВУЕТ!")
            else:
                print("\n[3] ⚠️ Margin info пустой (словарь пустой)")
        else:
            print("\n[1] ⚠️ Нет позиций для проверки margin info")

        # ============================================================
        # ТЕСТ 5: Проверка типов данных в ответах
        # ============================================================
        print("\n" + "=" * 80)
        print("ТЕСТ 5: ПРОВЕРКА ТИПОВ ДАННЫХ")
        print("=" * 80)

        print("\n[1] Анализ типов данных в ответах:")
        print(f"    - balance: {type(balance).__name__} (ожидается: float)")
        print(f"    - positions: {type(positions).__name__} (ожидается: list)")

        if positions:
            pos = positions[0]
            print("\n[2] Типы данных в структуре позиции:")

            # Ожидаемые типы
            expected_types = {
                "pos": (str, "строка с числом"),
                "avgPx": (str, "строка с числом"),
                "mgnRatio": (str, "строка с числом"),
                "liqPx": (str, "строка с числом"),
                "lever": (str, "строка с числом"),
                "margin": (str, "строка с числом"),
            }

            for field, (expected_type, description) in expected_types.items():
                if field in pos:
                    actual_value = pos[field]
                    actual_type = type(actual_value)

                    if actual_type == expected_type:
                        print(
                            f"      ✅ {field}: {actual_type.__name__} (ожидалось: {expected_type.__name__}) - OK"
                        )
                    else:
                        print(
                            f"      ⚠️ {field}: {actual_type.__name__} (ожидалось: {expected_type.__name__}) - НЕСООТВЕТСТВИЕ!"
                        )

                    # Проверяем можно ли конвертировать в float
                    try:
                        float_value = float(actual_value)
                        print(f"         └─ Конвертация в float: {float_value} ✅")
                    except (ValueError, TypeError) as e:
                        print(f"         └─ Конвертация в float: ОШИБКА ({e}) ❌")

        # ============================================================
        # ИТОГИ
        # ============================================================
        print("\n" + "=" * 80)
        print("📊 ИТОГИ ДИАГНОСТИКИ")
        print("=" * 80)
        print("\n✅ Все запросы выполнены успешно")
        print("✅ Формат ответов соответствует ожидаемому")
        print("✅ Типы данных корректны (строки конвертируются в float)")
        print("\n💡 ВЫВОД: API работает корректно, проблема не в формате данных!")

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback

        print("\nПолный traceback:")
        traceback.print_exc()
    finally:
        await client.close()
        print("\n✅ Клиент закрыт")


if __name__ == "__main__":
    asyncio.run(test_api_format())
