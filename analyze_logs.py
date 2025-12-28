#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализ логов торгового бота"""

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def analyze_csv(csv_path):
    """Анализ CSV файла с данными"""
    results = {
        "total_signals": 0,
        "total_orders": 0,
        "total_positions": 0,
        "total_trades": 0,
        "trades_by_reason": defaultdict(int),
        "trades_by_symbol": defaultdict(int),
        "profitable_trades": 0,
        "losing_trades": 0,
        "total_gross_pnl": 0.0,
        "total_net_pnl": 0.0,
        "total_commission": 0.0,
        "avg_duration": 0.0,
        "trades": [],
    }

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["record_type"] == "signals":
                results["total_signals"] += 1
            elif row["record_type"] == "orders":
                results["total_orders"] += 1
            elif row["record_type"] == "positions_open":
                results["total_positions"] += 1
            elif row["record_type"] == "trades":
                results["total_trades"] += 1
                symbol = row["symbol"]
                reason = row["reason"]
                net_pnl = float(row["net_pnl"]) if row["net_pnl"] else 0.0
                gross_pnl = float(row["gross_pnl"]) if row["gross_pnl"] else 0.0
                commission = float(row["commission"]) if row["commission"] else 0.0
                duration = float(row["duration_sec"]) if row["duration_sec"] else 0.0

                results["trades_by_reason"][reason] += 1
                results["trades_by_symbol"][symbol] += 1

                if net_pnl > 0:
                    results["profitable_trades"] += 1
                else:
                    results["losing_trades"] += 1

                results["total_gross_pnl"] += gross_pnl
                results["total_net_pnl"] += net_pnl
                results["total_commission"] += commission
                results["avg_duration"] += duration

                results["trades"].append(
                    {
                        "symbol": symbol,
                        "side": row["side"],
                        "entry_price": float(row["entry_price"])
                        if row["entry_price"]
                        else 0.0,
                        "exit_price": float(row["exit_price"])
                        if row["exit_price"]
                        else 0.0,
                        "size": float(row["size"]) if row["size"] else 0.0,
                        "gross_pnl": gross_pnl,
                        "net_pnl": net_pnl,
                        "commission": commission,
                        "duration": duration,
                        "reason": reason,
                        "timestamp": row["timestamp"],
                    }
                )

    if results["total_trades"] > 0:
        results["avg_duration"] /= results["total_trades"]

    return results


if __name__ == "__main__":
    csv_path = Path(
        "logs/futures/archived/logs_2025-12-28_10-22-50/all_data_2025-12-27.csv"
    )
    if csv_path.exists():
        results = analyze_csv(csv_path)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(f"Файл не найден: {csv_path}")
