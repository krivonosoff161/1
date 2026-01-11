#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Analyze closed positions from CSV"""

import csv

csv_path = (
    "logs\\futures\\archived\\staging_2026-01-11_21-27-02\\all_data_2026-01-11.csv"
)

with open(csv_path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)

    print("=== ЗАКРЫТЫЕ ПОЗИЦИИ С P&L ===\n")
    count = 0
    total_pnl = 0.0

    for row in reader:
        if row.get("exit_price") and row["exit_price"].strip():
            count += 1
            symbol = row.get("symbol", "N/A")
            side = row.get("side", "N/A").upper()
            entry_price = row.get("entry_price", "N/A")
            exit_price = row.get("exit_price", "N/A")
            size = row.get("size", "N/A")
            duration = row.get("duration_sec", "N/A")
            gross_pnl = float(row.get("gross_pnl", 0) or 0)
            commission = float(row.get("commission", 0) or 0)
            net_pnl = float(row.get("net_pnl", 0) or 0)
            reason = row.get("reason", "N/A")
            timestamp = row.get("timestamp", "N/A")

            total_pnl += net_pnl

            print(f"{count}. {symbol} {side} @ {timestamp}")
            print(f"   Entry: ${entry_price}, Exit: ${exit_price}")
            print(f"   Size: {size}, Duration: {duration}s")
            print(f"   Gross: ${gross_pnl}, Commission: ${commission}, NET: ${net_pnl}")
            print(f"   Reason: {reason}")
            print()

    print("=" * 50)
    print(f"ИТОГО: {count} закрытых позиций")
    print(f"ОБЩИЙ P&L: ${total_pnl:,.2f}")
    print("=" * 50)
