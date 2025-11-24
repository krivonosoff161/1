#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Глубокий анализ critical_loss_cut_2x из CSV и кода"""

import csv
from collections import defaultdict

# Читаем CSV
trades = []
with open('logs/trades_2025-11-23.csv', 'r', encoding='utf-8') as f:
    trades = list(csv.DictReader(f))

print("=" * 80)
print("ГЛУБОКИЙ АНАЛИЗ critical_loss_cut_2x")
print("=" * 80)

# Анализ критических закрытий
critical = [t for t in trades if 'critical_loss_cut_2x' in t.get('reason', '')]
zero_duration = [t for t in critical if float(t.get('duration_sec', 0) or 0) == 0]

print(f"\nВсего critical_loss_cut_2x: {len(critical)}")
print(f"С нулевым duration: {len(zero_duration)} ({len(zero_duration)/len(critical)*100:.1f}%)")

# Анализируем нулевые duration
print("\n" + "=" * 80)
print("АНАЛИЗ СДЕЛОК С НУЛЕВЫМ DURATION:")
print("=" * 80)

for i, t in enumerate(zero_duration[:10], 1):
    entry = float(t.get('entry_price', 0))
    exit_px = float(t.get('exit_price', 0))
    pnl = float(t.get('net_pnl', 0))
    side = t.get('side', '')
    
    if side == 'long':
        price_change_pct = ((exit_px - entry) / entry) * 100
    else:
        price_change_pct = ((entry - exit_px) / entry) * 100
    
    print(f"\n{i}. {t.get('symbol')} {side.upper()}")
    print(f"   Entry: ${entry:.4f} → Exit: ${exit_px:.4f}")
    print(f"   Изменение цены: {price_change_pct:.4f}%")
    print(f"   Net PnL: ${pnl:.4f}")
    print(f"   Commission: ${float(t.get('commission', 0)):.4f}")
    print(f"   Timestamp: {t.get('timestamp', '')[:19]}")

# Проверяем прибыльные critical_loss_cut
profitable_critical = [t for t in critical if float(t.get('net_pnl', 0)) > 0]
print(f"\n" + "=" * 80)
print(f"ПРИБЫЛЬНЫЕ critical_loss_cut_2x: {len(profitable_critical)}")
print("=" * 80)

for t in profitable_critical[:5]:
    print(f"{t.get('symbol')} {t.get('side')}: PnL=${float(t.get('net_pnl', 0)):.4f}, duration={float(t.get('duration_sec', 0)):.1f}s")

