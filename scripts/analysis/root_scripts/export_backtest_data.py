"""
Скрипт для экспорта данных для backtest стратегии.

Экспортирует:
1. Исторические OHLCV свечи (1-минутные) из OKX API
2. Сигналы входа из signals.csv
3. Логи сделок из trades.csv
4. Режимы рынка (если доступны)
"""

import asyncio
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import aiohttp


async def get_historical_candles(
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    timeframe: str = "1m",
    session: aiohttp.ClientSession = None,
) -> List[Dict[str, Any]]:
    """
    Получить исторические свечи из OKX API.

    Args:
        symbol: Торговый символ (например, BTC-USDT)
        start_time: Начальное время
        end_time: Конечное время
        timeframe: Таймфрейм (1m, 5m, 15m, 1H, etc.)
        session: aiohttp сессия (опционально)

    Returns:
        Список свечей в формате [timestamp, open, high, low, close, volume]
    """
    inst_id = f"{symbol}-SWAP"
    url = "https://www.okx.com/api/v5/market/history-candles"

    # OKX API ограничение: максимум 100 свечей за запрос
    # Нужно делать несколько запросов для больших периодов
    all_candles = []
    current_time = end_time

    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        while current_time >= start_time:
            # OKX принимает время в миллисекундах (ISO 8601 или timestamp)
            after = int(current_time.timestamp() * 1000)

            params = {
                "instId": inst_id,
                "bar": timeframe,
                "after": str(after),
                "limit": "100",  # Максимум за запрос
            }

            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == "0" and data.get("data"):
                        candles = data["data"]
                        if not candles:
                            break

                        # OKX формат: [timestamp, open, high, low, close, volume, volumeCcy, confirm]
                        for candle in candles:
                            if len(candle) >= 6:
                                candle_time = datetime.fromtimestamp(
                                    int(candle[0]) / 1000, tz=timezone.utc
                                )

                                # Проверяем, что свеча в нужном диапазоне
                                if candle_time < start_time:
                                    # Если вышли за пределы, прекращаем
                                    return all_candles

                                all_candles.append(
                                    {
                                        "timestamp": candle[0],  # В миллисекундах
                                        "datetime": candle_time.isoformat(),
                                        "open": float(candle[1]),
                                        "high": float(candle[2]),
                                        "low": float(candle[3]),
                                        "close": float(candle[4]),
                                        "volume": float(candle[5]),
                                        "volumeCcy": float(candle[6])
                                        if len(candle) > 6
                                        else 0.0,
                                    }
                                )

                        # Обновляем время для следующего запроса
                        # Берем timestamp самой старой свечи из текущего запроса
                        oldest_timestamp = int(candles[-1][0])
                        current_time = datetime.fromtimestamp(
                            oldest_timestamp / 1000, tz=timezone.utc
                        ) - timedelta(
                            minutes=1
                        )  # Минус 1 минута для следующего запроса
                    else:
                        print(
                            f"⚠️ API error для {symbol}: {data.get('msg', 'Unknown')}"
                        )
                        break
                else:
                    print(f"⚠️ HTTP error для {symbol}: {resp.status}")
                    break

        # Сортируем по времени (от старых к новым)
        all_candles.sort(key=lambda x: int(x["timestamp"]))
        return all_candles

    finally:
        if close_session:
            await session.close()


async def export_backtest_data(
    symbols: List[str],
    start_date: str,
    end_date: str,
    output_file: str = "backtest_data.json",
):
    """
    Экспортировать все данные для backtest.

    Args:
        symbols: Список символов для экспорта
        start_date: Начальная дата (YYYY-MM-DD)
        end_date: Конечная дата (YYYY-MM-DD)
        output_file: Имя выходного файла
    """
    start_time = datetime.fromisoformat(f"{start_date}T00:00:00+00:00")
    end_time = datetime.fromisoformat(f"{end_date}T23:59:59+00:00")

    print(f"📊 Экспорт данных для backtest:")
    print(f"   Период: {start_date} - {end_date}")
    print(f"   Символы: {', '.join(symbols)}")
    print(f"   Выходной файл: {output_file}")
    print()

    # 1. Получаем исторические свечи
    print("🕯️ Получение исторических свечей...")
    candles_data = {}

    async with aiohttp.ClientSession() as session:
        for symbol in symbols:
            print(f"   {symbol}...", end=" ", flush=True)
            candles = await get_historical_candles(
                symbol, start_time, end_time, "1m", session
            )
            candles_data[symbol] = candles
            print(f"✅ {len(candles)} свечей")
            await asyncio.sleep(0.5)  # Задержка между запросами

    # 2. Читаем сигналы из signals.csv
    print("\n📈 Чтение сигналов входа...")
    signals = []
    signals_file = Path("logs/signals_2025-12-17.csv")
    if signals_file.exists():
        with open(signals_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                signals.append(row)
        print(f"   ✅ {len(signals)} сигналов")
    else:
        print(f"   ⚠️ Файл {signals_file} не найден")

    # 3. Читаем сделки из trades.csv
    print("\n💰 Чтение логов сделок...")
    trades = []
    trades_file = Path("logs/trades_2025-12-17.csv")
    if trades_file.exists():
        with open(trades_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(row)
        print(f"   ✅ {len(trades)} сделок")
    else:
        print(f"   ⚠️ Файл {trades_file} не найден")

    # 4. Собираем все в один JSON
    print("\n💾 Сохранение данных...")
    output_data = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "start_date": start_date,
            "end_date": end_date,
            "symbols": symbols,
            "timeframe": "1m",
            "total_candles": sum(len(c) for c in candles_data.values()),
            "total_signals": len(signals),
            "total_trades": len(trades),
        },
        "candles": candles_data,
        "signals": signals,
        "trades": trades,
        "config": {
            "note": "Конфигурация стратегии в FINAL_CORRECTIONS_2025-12-08.json"
        },
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"   ✅ Данные сохранены в {output_file}")
    print(f"\n📊 Итого:")
    print(f"   Свечи: {output_data['metadata']['total_candles']}")
    print(f"   Сигналы: {len(signals)}")
    print(f"   Сделки: {len(trades)}")


async def main():
    """Главная функция"""
    # Параметры экспорта
    symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "XRP-USDT"]
    start_date = "2025-12-17"  # Дата начала
    end_date = "2025-12-17"  # Дата конца

    await export_backtest_data(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        output_file="backtest_data_2025-12-17.json",
    )


if __name__ == "__main__":
    asyncio.run(main())
