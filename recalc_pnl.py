#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Recalculate P&L with correct commission rates"""

# Реальные данные с биржи
positions = [
    {
        "symbol": "SOL-USDT",
        "side": "SHORT",
        "entry_price": 138.93692307692308,
        "exit_price": 137.0800,
        "size_coins": 1.82,
        "entry_commission_pct": 0.0005,  # taker
        "exit_commission_pct": 0.0005,  # taker
    },
    {
        "symbol": "XRP-USDT",
        "side": "LONG",
        "entry_price": 2.1012,
        "exit_price": 2.1129,
        "size_coins": 110.0,
        "entry_commission_pct": 0.0005,
        "exit_commission_pct": 0.0005,
    },
    {
        "symbol": "XRP-USDT",
        "side": "SHORT",
        "entry_price": 2.0971,
        "exit_price": 2.0900,
        "size_coins": 119.0,
        "entry_commission_pct": 0.0005,
        "exit_commission_pct": 0.0005,
    },
]

print("=" * 70)
print("ПЕРЕСЧЁТ P&L С ПРАВИЛЬНЫМИ КОМИССИЯМИ (0.02% maker / 0.05% taker)")
print("=" * 70)
print()

total_net_pnl = 0.0

for pos in positions:
    symbol = pos["symbol"]
    side = pos["side"]
    entry_price = pos["entry_price"]
    exit_price = pos["exit_price"]
    size_coins = pos["size_coins"]

    # Для маржинальной торговли 10x:
    # Реальный капитал = размер позиции / 10
    # Но P&L рассчитывается на реальный размер в монетах

    # Gross PnL calculation
    if side == "LONG":
        gross_pnl = (exit_price - entry_price) * size_coins
    else:  # SHORT
        gross_pnl = (entry_price - exit_price) * size_coins

    # Commission calculation - на маржинальный размер
    notional_entry = size_coins * entry_price
    notional_exit = size_coins * exit_price

    entry_commission = notional_entry * pos["entry_commission_pct"]
    exit_commission = notional_exit * pos["exit_commission_pct"]
    total_commission = entry_commission + exit_commission

    # Net PnL
    net_pnl = gross_pnl - total_commission

    # Percentage от реального капитала (на 10x левередже)
    # Реальная маржа = notional / 10
    real_margin = notional_entry / 10
    pnl_pct_on_margin = (net_pnl / real_margin) * 100

    total_net_pnl += net_pnl

    print(f"{symbol} {side}")
    print(f"  Entry: ${entry_price:.4f} | Exit: ${exit_price:.4f} | Size: {size_coins}")
    print(f"  Notional: ${notional_entry:,.2f} (маржа для 10x: ${real_margin:,.2f})")
    print(f"  Gross PnL: ${gross_pnl:,.4f}")
    print(f"  Commission: ${total_commission:,.4f}")
    print(f"  NET PnL: ${net_pnl:,.4f} ({pnl_pct_on_margin:+.2f}% на маржу)")
    print()

print("=" * 70)
print(f"ИТОГО NET PnL: ${total_net_pnl:,.4f}")
print("=" * 70)

# Сравнение с данными биржи
print("\nСРАВНЕНИЕ С БИРЖЕЙ:")
print("=" * 70)
print("Биржа показывает:")
print("  SOL SHORT: +0.60 USDT")
print("  XRP LONG:  +1.05 USDT")
print("  XRP SHORT: +0.67 USDT")
print("  ИТОГО:     +2.32 USDT")
print()
print(f"Бот рассчитал: ${total_net_pnl:,.4f}")
