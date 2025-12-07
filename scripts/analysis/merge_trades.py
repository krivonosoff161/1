#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Объединение сделок за 2 и 3 декабря 2025 в один файл
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def load_trades_from_json(filepath: Path) -> List[Dict]:
    """Загружает сделки из JSON файла"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_trades(files: List[Path]) -> List[Dict]:
    """Объединяет сделки из нескольких файлов"""
    all_trades = []

    for filepath in files:
        print(f"📂 Загружаю {filepath.name}...")
        trades = load_trades_from_json(filepath)
        print(f"   Найдено {len(trades)} сделок")
        all_trades.extend(trades)

    # Сортируем по времени (от старых к новым)
    all_trades.sort(key=lambda x: x.get("timestamp", ""))

    return all_trades


def save_to_json(trades: List[Dict], filename: str):
    """Сохраняет сделки в JSON файл"""
    output_path = Path(filename)
    output_path.write_text(
        json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n💾 Объединенные сделки сохранены в {output_path}")


def save_to_csv(trades: List[Dict], filename: str):
    """Сохраняет сделки в CSV файл"""
    import csv

    if not trades:
        print("⚠️ Нет данных для сохранения")
        return

    output_path = Path(filename)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)

    print(f"💾 Объединенные сделки сохранены в {output_path}")


def print_summary(trades: List[Dict]):
    """Выводит сводку по объединенным сделкам"""
    if not trades:
        print("\n⚠️ Нет сделок для анализа")
        return

    print("\n" + "=" * 80)
    print("📊 СВОДКА ПО ОБЪЕДИНЕННЫМ СДЕЛКАМ")
    print("=" * 80)

    # Группировка по символам
    by_symbol = {}
    for trade in trades:
        symbol = trade.get("symbol", "UNKNOWN")
        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(trade)

    print(f"\nВсего сделок: {len(trades)}")
    print(f"Символов: {len(by_symbol)}")

    # Статистика по каждому символу
    for symbol, symbol_trades in sorted(by_symbol.items()):
        buys = [t for t in symbol_trades if t.get("side") == "buy"]
        sells = [t for t in symbol_trades if t.get("side") == "sell"]

        total_fee = sum(abs(float(t.get("fee", 0) or 0)) for t in symbol_trades)
        total_pnl = sum(
            float(t.get("pnl") or 0) for t in symbol_trades if t.get("pnl") is not None
        )

        print(f"\n{symbol}:")
        print(
            f"  Всего: {len(symbol_trades)} (покупок: {len(buys)}, продаж: {len(sells)})"
        )
        print(f"  Комиссия: {total_fee:.4f}")
        if total_pnl != 0:
            print(f"  PnL: {total_pnl:.4f}")

    # Временной диапазон
    if trades:
        first_time = trades[0].get("timestamp", "")
        last_time = trades[-1].get("timestamp", "")
        print(f"\nПериод: {first_time} - {last_time}")

        # Группировка по датам
        from collections import defaultdict

        by_date = defaultdict(int)
        for trade in trades:
            timestamp = trade.get("timestamp", "")
            if timestamp:
                date = timestamp.split("T")[0]
                by_date[date] += 1

        print(f"\nПо датам:")
        for date in sorted(by_date.keys()):
            print(f"  {date}: {by_date[date]} сделок")


def main():
    """Главная функция"""
    print("=" * 80)
    print("🔗 ОБЪЕДИНЕНИЕ СДЕЛОК ЗА 2 И 3 ДЕКАБРЯ 2025")
    print("=" * 80)

    # Ищем файлы за 2 и 3 число
    current_dir = Path(".")

    # Файлы, которые были созданы ранее
    files_to_merge = []

    # Ищем файлы за 2 и 3 число
    # По времени создания: 20:06:04 - за 2 число, 20:06:57 - за 3 число
    json_files = list(current_dir.glob("trades_all_*.json"))

    # Сортируем по времени создания
    json_files.sort(key=lambda x: x.stat().st_mtime)

    # Берем файлы за 2 и 3 число (предпоследний и последний из отсортированных)
    if len(json_files) >= 2:
        # Последние 2 файла должны быть за 2 и 3 число
        files_to_merge = json_files[-2:]
        print(f"\n📁 Найдено файлов для объединения: {len(files_to_merge)}")
        for f in files_to_merge:
            print(
                f"   - {f.name} (создан: {datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')})"
            )
    else:
        print(f"\n❌ Не найдено достаточно файлов для объединения")
        print(f"   Найдено файлов: {len(json_files)}")
        if json_files:
            print("   Доступные файлы:")
            for f in json_files:
                print(f"     - {f.name}")
        return

    # Объединяем
    merged_trades = merge_trades(files_to_merge)

    if not merged_trades:
        print("\n❌ Нет сделок для объединения")
        return

    # Выводим сводку
    print_summary(merged_trades)

    # Сохраняем объединенный файл
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_file = f"trades_merged_02-03_12_2025_{timestamp}.json"
    csv_file = f"trades_merged_02-03_12_2025_{timestamp}.csv"

    save_to_json(merged_trades, json_file)
    save_to_csv(merged_trades, csv_file)

    print("\n" + "=" * 80)
    print("✅ ОБЪЕДИНЕНИЕ ЗАВЕРШЕНО")
    print("=" * 80)


if __name__ == "__main__":
    main()
