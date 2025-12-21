# -*- coding: utf-8 -*-
"""Быстрый ручной анализ логов без полной загрузки в память"""

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

log_dir = Path(
    r"c:\Users\krivo\simple trading bot okx\logs\futures\archived\logs_2025-12-18_19-46-30"
)

stats = {
    "positions_opened": 0,
    "positions_closed": 0,
    "positions_profitable": 0,
    "positions_loss": 0,
    "total_pnl": 0.0,
    "orders_placed": 0,
    "orders_filled": 0,
    "errors": defaultdict(int),
    "warnings": defaultdict(int),
    "balances": [],
    "start_time": None,
    "end_time": None,
}

# Паттерны для поиска
patterns = {
    "position_open": re.compile(r"✅\s*[Пп]озиция\s+(\S+)\s+открыт", re.I),
    "position_close": re.compile(r"✅\s*[Пп]озиция\s+(\S+)\s+закрыт", re.I),
    "pnl": re.compile(r"pnl\s*[=:]\s*([\+\-]?\d+\.?\d*)\s*usdt", re.I),
    "equity": re.compile(r"equity[=:]\s*(\d+\.?\d*)", re.I),
    "order_placed": re.compile(
        r"(?:🎯.*исполнение сигнала|размещение.*ордер|ордер размещен)", re.I
    ),
    "order_filled": re.compile(r"(?:order filled|ордер исполнен)", re.I),
    "error": re.compile(r"ERROR\s*\|\s*([^|]+)", re.I),
    "warning": re.compile(r"WARNING\s*\|\s*([^|]+)", re.I),
    "timestamp": re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"),
}

print("Анализирую логи...")
log_files = list(log_dir.glob("*.log"))
print(f"Найдено {len(log_files)} файлов")

for log_file in log_files:
    if "error" in log_file.name.lower():
        continue  # Пропускаем файл ошибок, его обработаем отдельно

    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                # Временные метки
                time_match = patterns["timestamp"].search(line)
                if time_match:
                    try:
                        dt = datetime.strptime(time_match.group(1), "%Y-%m-%d %H:%M:%S")
                        if stats["start_time"] is None or dt < stats["start_time"]:
                            stats["start_time"] = dt
                        if stats["end_time"] is None or dt > stats["end_time"]:
                            stats["end_time"] = dt
                    except:
                        pass

                # Позиции
                if patterns["position_open"].search(line):
                    stats["positions_opened"] += 1

                if patterns["position_close"].search(line):
                    stats["positions_closed"] += 1
                    # Ищем PnL в этой или следующих строках
                    pnl_match = patterns["pnl"].search(line)
                    if pnl_match:
                        pnl = float(pnl_match.group(1))
                        stats["total_pnl"] += pnl
                        if pnl > 0:
                            stats["positions_profitable"] += 1
                        else:
                            stats["positions_loss"] += 1

                # Ордера
                if patterns["order_placed"].search(line):
                    stats["orders_placed"] += 1

                if patterns["order_filled"].search(line):
                    stats["orders_filled"] += 1

                # Баланс
                equity_match = patterns["equity"].search(line)
                if equity_match:
                    balance = float(equity_match.group(1))
                    if balance > 100:  # Только реальные балансы
                        stats["balances"].append((line[:50], balance))

                # Ошибки и предупреждения
                if "| ERROR" in line:
                    error_match = patterns["error"].search(line)
                    if error_match:
                        error_msg = error_match.group(1)[:100]
                        stats["errors"][error_msg] += 1

                if "| WARNING" in line:
                    warn_match = patterns["warning"].search(line)
                    if warn_match:
                        warn_msg = warn_match.group(1)[:100]
                        stats["warnings"][warn_msg] += 1

                if line_num % 100000 == 0:
                    print(f"  Обработано {line_num} строк из {log_file.name}")

    except Exception as e:
        print(f"Ошибка чтения {log_file.name}: {e}")

# Анализ файла ошибок отдельно
error_file = log_dir / "errors_2025-12-18.log"
if error_file.exists():
    print("\nАнализирую файл ошибок...")
    with open(error_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "ERROR" in line:
                error_match = patterns["error"].search(line)
                if error_match:
                    error_msg = error_match.group(1)[:100]
                    stats["errors"][error_msg] += 1

# Вывод результатов
print("\n" + "=" * 80)
print("СТАТИСТИКА ЗА 2025-12-18")
print("=" * 80)

if stats["start_time"] and stats["end_time"]:
    duration = stats["end_time"] - stats["start_time"]
    print(f"\nВРЕМЕННЫЕ РАМКИ:")
    print(f"  Начало: {stats['start_time']}")
    print(f"  Конец:  {stats['end_time']}")
    print(f"  Длительность: {duration}")

if stats["balances"]:
    balances = [b[1] for b in stats["balances"]]
    start_balance = balances[0] if balances else 0
    end_balance = balances[-1] if balances else 0
    profit = end_balance - start_balance
    profit_percent = (profit / start_balance * 100) if start_balance > 0 else 0

    print(f"\nФИНАНСЫ:")
    print(f"  Начальный баланс: ${start_balance:.2f}")
    print(f"  Конечный баланс:  ${end_balance:.2f}")
    print(f"  Прибыль/Убыток:   ${profit:+.2f} ({profit_percent:+.2f}%)")

print(f"\nПОЗИЦИИ:")
print(f"  Открыто:       {stats['positions_opened']}")
print(f"  Закрыто:       {stats['positions_closed']}")
print(f"  Прибыльных:    {stats['positions_profitable']}")
print(f"  Убыточных:     {stats['positions_loss']}")
if stats["positions_closed"] > 0:
    win_rate = (stats["positions_profitable"] / stats["positions_closed"]) * 100
    avg_pnl = stats["total_pnl"] / stats["positions_closed"]
    print(f"  Винрейт:       {win_rate:.1f}%")
    print(f"  Общий PnL:     ${stats['total_pnl']:.2f}")
    print(f"  Средний PnL:   ${avg_pnl:.2f}")

print(f"\nОРДЕРА:")
print(f"  Размещено:     {stats['orders_placed']}")
print(f"  Исполнено:     {stats['orders_filled']}")
if stats["orders_placed"] > 0:
    effectiveness = (stats["orders_filled"] / stats["orders_placed"]) * 100
    print(f"  Эффективность: {effectiveness:.1f}%")

print(f"\nОШИБКИ (топ-10):")
sorted_errors = sorted(stats["errors"].items(), key=lambda x: x[1], reverse=True)
for i, (msg, count) in enumerate(sorted_errors[:10], 1):
    print(f"  {i}. [{count}x] {msg}")

print(f"\nПРЕДУПРЕЖДЕНИЯ (топ-10):")
sorted_warnings = sorted(stats["warnings"].items(), key=lambda x: x[1], reverse=True)
for i, (msg, count) in enumerate(sorted_warnings[:10], 1):
    print(f"  {i}. [{count}x] {msg}")

print("\n" + "=" * 80)
