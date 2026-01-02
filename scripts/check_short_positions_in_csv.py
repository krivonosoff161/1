#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки SHORT позиций в CSV файле
"""

import csv
from pathlib import Path
from collections import defaultdict

def analyze_csv_side_distribution(csv_path: str):
    """Анализ распределения side в CSV файле"""
    
    csv_file = Path(csv_path)
    if not csv_file.exists():
        print(f"❌ Файл не найден: {csv_path}")
        return
    
    print(f"📊 Анализ CSV файла: {csv_path}\n")
    print("=" * 80)
    
    trades = []
    side_distribution = defaultdict(int)
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('record_type') == 'trades':
                side = row.get('side', '').strip().lower()
                trades.append(row)
                side_distribution[side] += 1
    
    print(f"Всего сделок (trades): {len(trades)}\n")
    print("Распределение по сторонам:")
    for side, count in sorted(side_distribution.items()):
        print(f"  {side.upper()}: {count} ({count/len(trades)*100:.1f}%)")
    
    print("\n" + "=" * 80)
    print("SHORT позиции (первые 10):")
    print("=" * 80)
    
    short_trades = [t for t in trades if t.get('side', '').strip().lower() == 'short']
    
    if not short_trades:
        print("❌ SHORT позиции НЕ найдены в CSV!")
    else:
        print(f"✅ Найдено {len(short_trades)} SHORT позиций\n")
        for i, trade in enumerate(short_trades[:10], 1):
            print(f"{i}. {trade.get('timestamp', 'N/A')} | {trade.get('symbol', 'N/A')} | "
                  f"side={trade.get('side', 'N/A')} | entry={trade.get('entry_price', 'N/A')} | "
                  f"exit={trade.get('exit_price', 'N/A')} | pnl={trade.get('net_pnl', 'N/A')}")
    
    print("\n" + "=" * 80)
    print("LONG позиции (первые 5 для сравнения):")
    print("=" * 80)
    
    long_trades = [t for t in trades if t.get('side', '').strip().lower() == 'long']
    for i, trade in enumerate(long_trades[:5], 1):
        print(f"{i}. {trade.get('timestamp', 'N/A')} | {trade.get('symbol', 'N/A')} | "
              f"side={trade.get('side', 'N/A')} | entry={trade.get('entry_price', 'N/A')} | "
              f"exit={trade.get('exit_price', 'N/A')} | pnl={trade.get('net_pnl', 'N/A')}")

if __name__ == "__main__":
    csv_path = "logs/futures/archived/logs_2025-12-30_22-06-26/all_data_2025-12-30.csv"
    analyze_csv_side_distribution(csv_path)


