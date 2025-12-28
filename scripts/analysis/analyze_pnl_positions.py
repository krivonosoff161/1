"""
Анализ PnL открытых позиций из trades_2025-12-23.csv
"""
import csv
from datetime import datetime, timezone

import requests

# Текущие цены (можно получить через API)
CURRENT_PRICES = {
    "BTC-USDT": 89891.70,  # Примерная цена на момент анализа
    "ETH-USDT": 3019.84,  # Примерная цена на момент анализа
}


def analyze_positions():
    """Анализ PnL открытых позиций"""

    # Читаем CSV
    positions = []
    with open(
        "ANALYSIS_PACKAGE_2025-12-23/trades_2025-12-23.csv", "r", encoding="utf-8"
    ) as f:
        reader = csv.DictReader(f)
        for row in reader:
            # CSV использует кавычки, убираем их
            record_type = row.get("record_type", "").strip('"').strip()
            if record_type == "positions_open":
                # Очищаем все значения от кавычек
                clean_row = {
                    k: v.strip('"').strip() if v else "" for k, v in row.items()
                }
                positions.append(clean_row)

    print(f"Анализ {len(positions)} открытых позиций\n")
    print("=" * 80)

    total_pnl = 0.0
    eth_positions = []
    btc_positions = []

    for pos in positions:
        symbol = pos["symbol"]
        side = pos["side"]
        entry_price = float(pos["entry_price"])
        size = float(pos["size"])
        entry_time = pos["timestamp"]

        # Текущая цена
        current_price = CURRENT_PRICES.get(symbol, 0)
        if current_price == 0:
            print(f"⚠️ {symbol}: Текущая цена не найдена")
            continue

        # Расчет PnL
        if side == "long":
            price_diff = current_price - entry_price
        else:  # short
            price_diff = entry_price - current_price

        # PnL в USD (упрощенный расчет, без учета комиссии и маржи)
        pnl_usd = price_diff * size
        pnl_pct = (price_diff / entry_price) * 100 if entry_price > 0 else 0

        total_pnl += pnl_usd

        # Время в позиции
        try:
            entry_dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            duration = (now - entry_dt).total_seconds() / 3600  # часы
        except:
            duration = 0

        pos_data = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "current_price": current_price,
            "size": size,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "duration_hours": duration,
            "entry_time": entry_time,
        }

        if symbol == "ETH-USDT":
            eth_positions.append(pos_data)
        elif symbol == "BTC-USDT":
            btc_positions.append(pos_data)

        status = "[+]" if pnl_usd > 0 else "[-]"
        print(
            f"{status} {symbol} ({side}): entry=${entry_price:.2f}, current=${current_price:.2f}, "
            f"PnL=${pnl_usd:.2f} ({pnl_pct:+.2f}%), size={size}, duration={duration:.1f}h"
        )

    print("=" * 80)
    print(f"\nИТОГО:")
    print(f"  ETH-USDT позиций: {len(eth_positions)}")
    print(f"  BTC-USDT позиций: {len(btc_positions)}")
    print(f"  Общий PnL: ${total_pnl:.2f}")

    # Детализация по ETH
    if eth_positions:
        eth_total = sum(p["pnl_usd"] for p in eth_positions)
        print(f"\n  ETH-USDT PnL: ${eth_total:.2f}")
        avg_entry = sum(p["entry_price"] for p in eth_positions) / len(eth_positions)
        print(f"  ETH-USDT средняя цена входа: ${avg_entry:.2f}")

    # Детализация по BTC
    if btc_positions:
        btc_total = sum(p["pnl_usd"] for p in btc_positions)
        print(f"\n  BTC-USDT PnL: ${btc_total:.2f}")
        avg_entry = sum(p["entry_price"] for p in btc_positions) / len(btc_positions)
        print(f"  BTC-USDT средняя цена входа: ${avg_entry:.2f}")

    return positions, total_pnl


if __name__ == "__main__":
    analyze_positions()
