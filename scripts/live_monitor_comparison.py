"""
Скрипт для мониторинга и сравнения параметров бота с биржей в реальном времени.
Получает свечи 1m с OKX, вычисляет индикаторы и сравнивает с логами бота.
"""

import asyncio
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp

# Добавляем путь к src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indicators import (ATR, MACD, RSI, BollingerBands,
                            ExponentialMovingAverage)


async def get_okx_candles(symbol: str, limit: int = 100) -> List[Dict]:
    """Получает свечи 1m с OKX"""
    inst_id = f"{symbol}-SWAP"
    url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1m&limit={limit}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("code") == "0" and data.get("data"):
                    return data["data"]
    return []


def parse_candles(candles: List[List]) -> List[Dict]:
    """Парсит свечи в удобный формат"""
    result = []
    for candle in reversed(candles):  # OKX возвращает в обратном порядке
        result.append(
            {
                "timestamp": int(candle[0]),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            }
        )
    return result


def calculate_indicators(candles: List[Dict]) -> Dict:
    """Вычисляет индикаторы из свечей"""
    closes = [c["close"] for c in candles]

    result = {
        "current_price": candles[-1]["close"] if candles else None,
    }

    try:
        # RSI
        rsi_ind = RSI(period=14, overbought=70, oversold=30)
        rsi_result = rsi_ind.calculate(closes)
        result["rsi"] = rsi_result.value if rsi_result else 50.0
    except Exception as e:
        result["rsi"] = None
        print(f"  ⚠️ Ошибка расчета RSI: {e}")

    try:
        # MACD
        macd_ind = MACD(fast_period=12, slow_period=26, signal_period=9)
        macd_result = macd_ind.calculate(closes)
        result["macd_metadata"] = (
            macd_result.metadata
            if macd_result and hasattr(macd_result, "metadata")
            else {}
        )
    except Exception as e:
        result["macd_metadata"] = {}
        print(f"  ⚠️ Ошибка расчета MACD: {e}")

    try:
        # ATR требует high_data, low_data, close_data
        atr_ind = ATR(period=14)
        if len(candles) >= 14:
            high_data = [c["high"] for c in candles]
            low_data = [c["low"] for c in candles]
            close_data = [c["close"] for c in candles]
            atr_result = atr_ind.calculate(high_data, low_data, close_data)
            result["atr"] = atr_result.value if atr_result else None
        else:
            result["atr"] = None
    except Exception as e:
        result["atr"] = None
        print(f"  ⚠️ Ошибка расчета ATR: {e}")

    try:
        # Bollinger Bands
        bb_ind = BollingerBands(period=20, std_multiplier=2.0)
        bb_result = bb_ind.calculate(closes)
        result["bb"] = (
            bb_result.metadata if bb_result and hasattr(bb_result, "metadata") else {}
        )
    except Exception as e:
        result["bb"] = {}
        print(f"  ⚠️ Ошибка расчета BB: {e}")

    try:
        # EMA
        ema_12 = ExponentialMovingAverage(period=12)
        ema_26 = ExponentialMovingAverage(period=26)
        ema_12_result = ema_12.calculate(closes) if len(closes) >= 12 else None
        ema_26_result = ema_26.calculate(closes) if len(closes) >= 26 else None
        result["ema_12"] = ema_12_result.value if ema_12_result else None
        result["ema_26"] = ema_26_result.value if ema_26_result else None
    except Exception as e:
        result["ema_12"] = None
        result["ema_26"] = None
        print(f"  ⚠️ Ошибка расчета EMA: {e}")

    return result


def parse_log_line(line: str) -> Optional[Dict]:
    """Парсит строку лога и извлекает информацию"""
    result = {}

    # Ищем RSI
    rsi_match = re.search(r"RSI.*?значение=([\d.]+)", line)
    if rsi_match:
        result["rsi"] = float(rsi_match.group(1))

    # Ищем режим ARM
    regime_match = re.search(r"ARM режим.*?([\w]+)", line)
    if regime_match:
        result["regime"] = regime_match.group(1)

    # Ищем цену
    price_match = re.search(r"\$\s*([\d,.]+)", line)
    if price_match:
        result["price"] = float(price_match.group(1).replace(",", ""))

    # Ищем индикаторы
    if "BTC-USDT" in line or "ETH-USDT" in line:
        result["symbol"] = "BTC-USDT" if "BTC-USDT" in line else "ETH-USDT"

    return result if result else None


async def monitor_comparison():
    """Основной цикл мониторинга"""
    # Ищем актуальный лог файл
    log_dir = Path("logs")
    log_files = list(log_dir.glob("futures_main_*.log")) + list(
        log_dir.glob("trading_bot_*.log")
    )
    log_file = log_files[0] if log_files else Path("logs/futures_main_2025-11-03.log")
    symbols = ["BTC-USDT", "ETH-USDT"]

    print("=" * 80)
    print("🔍 МОНИТОРИНГ В РЕАЛЬНОМ ВРЕМЕНИ")
    print("=" * 80)
    print(f"📊 Символы: {', '.join(symbols)}")
    print(f"⏰ Таймфрейм: 1m")
    print(f"📁 Логи: {log_file}")
    print("=" * 80)
    print()

    # Получаем свежие свечи
    for symbol in symbols:
        print(f"\n📈 {symbol}:")
        candles_data = await get_okx_candles(symbol, limit=100)
        if not candles_data:
            print(f"  ❌ Не удалось получить свечи для {symbol}")
            continue

        candles = parse_candles(candles_data)
        indicators = calculate_indicators(candles)

        print(f"  💰 Цена: ${indicators['current_price']:,.2f}")
        print(f"  📊 RSI: {indicators['rsi']:.2f}")

        if indicators["macd_metadata"]:
            macd = indicators["macd_metadata"].get("macd", 0)
            signal = indicators["macd_metadata"].get("signal", 0)
            histogram = indicators["macd_metadata"].get("histogram", 0)
            print(
                f"  📊 MACD: {macd:.4f} | Signal: {signal:.4f} | Histogram: {histogram:.4f}"
            )

        if indicators["atr"]:
            print(f"  📊 ATR: {indicators['atr']:.2f}")

        if indicators["bb"]:
            upper = indicators["bb"].get("upper", 0)
            middle = indicators["bb"].get("middle", 0)
            lower = indicators["bb"].get("lower", 0)
            print(
                f"  📊 BB: Upper={upper:.2f} | Middle={middle:.2f} | Lower={lower:.2f}"
            )

        if indicators["ema_12"] and indicators["ema_26"]:
            print(
                f"  📊 EMA: 12={indicators['ema_12']:.2f} | 26={indicators['ema_26']:.2f}"
            )

    # Читаем последние строки логов
    print("\n" + "=" * 80)
    print("📋 ПОСЛЕДНИЕ ЛОГИ БОТА:")
    print("=" * 80)

    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Последние 30 строк с индикаторами
            relevant_lines = [
                l
                for l in lines[-50:]
                if any(
                    x in l for x in ["RSI", "ARM", "режим", "BTC-USDT", "ETH-USDT", "$"]
                )
            ]

            for line in relevant_lines[-10:]:
                parsed = parse_log_line(line.strip())
                if parsed:
                    timestamp = line[:19] if len(line) > 19 else ""
                    print(f"{timestamp} | {parsed}")
                else:
                    # Показываем важные строки
                    if any(keyword in line for keyword in ["💰", "📊", "🧠", "сигнал"]):
                        print(line.strip()[:120])
    else:
        print(f"  ⚠️ Лог файл не найден: {log_file}")

    print("\n" + "=" * 80)
    print("✅ Мониторинг завершен. Запустите снова для обновления данных.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(monitor_comparison())
