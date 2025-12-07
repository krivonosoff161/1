#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генерация маркет-данных (OHLCV) и Performance Report для аудита
"""

import asyncio
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np
import aiohttp
import yaml

# Символы для запроса
SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "XRP-USDT"]
DATE = "2025-12-07"
START_TIME = "2025-12-07T14:00:00Z"
END_TIME = "2025-12-07T15:30:00Z"

async def fetch_candles_okx(symbol: str, timeframe: str = "1m", limit: int = 200):
    """Получить свечи с OKX API"""
    inst_id = f"{symbol}-SWAP"
    url = "https://www.okx.com/api/v5/market/candles"
    
    # Конвертируем время в timestamp (миллисекунды)
    start_dt = datetime.fromisoformat(START_TIME.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(END_TIME.replace('Z', '+00:00'))
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    
    # Пробуем без временных ограничений - просто последние свечи
    params = {
        "instId": inst_id,
        "bar": timeframe,
        "limit": str(limit)
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == "0" and data.get("data"):
                        candles = []
                        for candle_data in data["data"]:
                            if len(candle_data) >= 6:
                                ts_ms = int(candle_data[0])
                                ts_sec = ts_ms // 1000
                                candles.append({
                                    "timestamp": datetime.fromtimestamp(ts_sec, tz=timezone.utc).isoformat(),
                                    "symbol": symbol,
                                    "open": float(candle_data[1]),
                                    "high": float(candle_data[2]),
                                    "low": float(candle_data[3]),
                                    "close": float(candle_data[4]),
                                    "volume": float(candle_data[5]),
                                    "quote_currency": "USDT"
                                })
                        return candles
    except Exception as e:
        print(f"❌ Ошибка получения свечей для {symbol}: {e}")
    
    return []

async def generate_market_data():
    """Генерировать market_data.csv"""
    print("📊 Получение маркет-данных с OKX...")
    
    all_candles = []
    for symbol in SYMBOLS:
        print(f"   Запрашиваю {symbol}...")
        candles = await fetch_candles_okx(symbol, "1m", 200)
        all_candles.extend(candles)
        print(f"   ✅ Получено {len(candles)} свечей для {symbol}")
    
    # Сортируем по timestamp
    all_candles.sort(key=lambda x: x["timestamp"])
    
    # Сохраняем в CSV
    output_file = f"logs/futures/archived/logs_2025-12-07_16-03-39_extracted/market_data_{DATE}.csv"
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "symbol", "open", "high", "low", "close", "volume", "quote_currency"])
        writer.writeheader()
        writer.writerows(all_candles)
    
    print(f"✅ Маркет-данные сохранены: {output_file} ({len(all_candles)} свечей)")
    return output_file, all_candles

def calculate_performance_metrics(trades_df, market_data_df=None):
    """Рассчитать метрики производительности"""
    if len(trades_df) == 0:
        return {}
    
    # Базовые метрики
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df["net_pnl"] > 0])
    losing_trades = len(trades_df[trades_df["net_pnl"] < 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_pnl = float(trades_df["net_pnl"].sum())
    total_commission = float(trades_df["commission"].sum())
    gross_pnl = float(trades_df["gross_pnl"].sum())
    
    avg_trade = total_pnl / total_trades if total_trades > 0 else 0
    avg_winning_trade = float(trades_df[trades_df["net_pnl"] > 0]["net_pnl"].mean()) if winning_trades > 0 else 0
    avg_losing_trade = float(trades_df[trades_df["net_pnl"] < 0]["net_pnl"].mean()) if losing_trades > 0 else 0
    
    largest_win = float(trades_df["net_pnl"].max()) if total_trades > 0 else 0
    largest_loss = float(trades_df["net_pnl"].min()) if total_trades > 0 else 0
    
    # Profit Factor
    total_wins = float(trades_df[trades_df["net_pnl"] > 0]["net_pnl"].sum()) if winning_trades > 0 else 0
    total_losses = abs(float(trades_df[trades_df["net_pnl"] < 0]["net_pnl"].sum())) if losing_trades > 0 else 0
    profit_factor = total_wins / total_losses if total_losses > 0 else 0
    
    # Consecutive wins/losses
    consecutive_wins = 0
    consecutive_losses = 0
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    
    for pnl in trades_df["net_pnl"]:
        if pnl > 0:
            consecutive_wins += 1
            consecutive_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
        else:
            consecutive_losses += 1
            consecutive_wins = 0
            max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
    
    # Avg holding time
    avg_holding_minutes = float(trades_df["duration_sec"].mean() / 60) if "duration_sec" in trades_df.columns else 0
    
    metrics = {
        "sharpe_ratio": None,  # Требует returns
        "sortino_ratio": None,  # Требует returns
        "calmar_ratio": None,  # Требует CAGR и max_dd
        "cagr": None,  # Требует период и начальный капитал
        "max_drawdown": None,  # Требует equity curve
        "max_drawdown_duration": None,
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor > 0 else 0,
        "avg_trade": round(avg_trade, 4),
        "avg_winning_trade": round(avg_winning_trade, 4),
        "avg_losing_trade": round(avg_losing_trade, 4),
        "avg_bars_in_trade": None,  # Требует market data
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "total_pnl": round(total_pnl, 4),
        "total_commission": round(total_commission, 4),
        "net_pnl": round(total_pnl, 4),
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
        "largest_win": round(largest_win, 4),
        "largest_loss": round(largest_loss, 4),
        "avg_holding_time_minutes": round(avg_holding_minutes, 2)
    }
    
    return metrics

def generate_performance_report(trades_file, market_data_file=None):
    """Генерировать performance_report.yaml"""
    print("\n📈 Генерация Performance Report...")
    
    # Читаем trades
    trades_df = pd.read_csv(trades_file)
    
    # Рассчитываем метрики
    metrics = calculate_performance_metrics(trades_df)
    
    # Формируем отчет
    report = {
        "metrics": metrics,
        "period": {
            "start": DATE,
            "end": DATE,
            "days": 1
        },
        "benchmark": {
            "name": None,
            "return": None,
            "sharpe": None
        },
        "additional": {
            "max_consecutive_wins": metrics.get("max_consecutive_wins", 0),
            "max_consecutive_losses": metrics.get("max_consecutive_losses", 0),
            "largest_win": metrics.get("largest_win", 0),
            "largest_loss": metrics.get("largest_loss", 0),
            "avg_holding_time_minutes": metrics.get("avg_holding_time_minutes", 0)
        }
    }
    
    # Сохраняем
    output_file = f"logs/futures/archived/logs_2025-12-07_16-03-39_extracted/performance_report_{DATE}.yaml"
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.dump(report, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    print(f"✅ Performance Report сохранен: {output_file}")
    return output_file

async def main():
    """Основная функция"""
    print("=" * 70)
    print("📊 ГЕНЕРАЦИЯ ДАННЫХ ДЛЯ АУДИТА")
    print("=" * 70)
    
    # 1. Генерируем маркет-данные
    market_data_file, candles = await generate_market_data()
    
    # 2. Генерируем Performance Report
    trades_file = "logs/futures/archived/logs_2025-12-07_16-03-39_extracted/trades_2025-12-07.csv"
    if Path(trades_file).exists():
        performance_file = generate_performance_report(trades_file, market_data_file)
        print(f"\n✅ Все данные сгенерированы!")
        print(f"   📄 Market Data: {market_data_file}")
        print(f"   📄 Performance Report: {performance_file}")
    else:
        print(f"\n⚠️ Файл trades не найден: {trades_file}")

if __name__ == "__main__":
    asyncio.run(main())

