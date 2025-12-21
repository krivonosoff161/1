# -*- coding: utf-8 -*-
"""Комплексный анализ всех логов из архива"""

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Настройка кодировки для Windows
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

log_dir = Path(r"c:\Users\krivo\simple trading bot okx\logs\futures\archived")

# Статистика по всем дням
all_stats = {}

# Паттерны для поиска
patterns = {
    "position_open": re.compile(r"✅\s*[Пп]озиция\s+(\S+)\s+открыт", re.I),
    "position_close": re.compile(r"✅\s*[Пп]озиция\s+(\S+)\s+закрыт", re.I),
    "pnl": re.compile(r"pnl\s*[=:]\s*([\+\-]?\d+\.?\d*)\s*usdt", re.I),
    "pnl_percent": re.compile(r"pnl[%:]\s*([\+\-]?\d+\.?\d*)", re.I),
    "equity": re.compile(r"equity[=:]\s*(\d+\.?\d*)", re.I),
    "order_placed": re.compile(
        r"(?:🎯.*исполнение сигнала|размещение.*ордер|ордер размещен)", re.I
    ),
    "order_filled": re.compile(r"(?:order filled|ордер исполнен)", re.I),
    "order_cancelled": re.compile(r"(?:order cancelled|ордер отменен)", re.I),
    "error": re.compile(r"ERROR\s*\|\s*([^|]+)", re.I),
    "warning": re.compile(r"WARNING\s*\|\s*([^|]+)", re.I),
    "timestamp": re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})"),
    "signal_generated": re.compile(r"(?:сигнал.*сгенерирован|signal.*generated)", re.I),
    "signal_executed": re.compile(r"(?:сигнал.*исполнен|signal.*executed)", re.I),
    "timeout": re.compile(r"timeout|таймаут", re.I),
    "51006": re.compile(r"51006|price limit|цена.*лимит", re.I),
}

print("=" * 80)
print("КОМПЛЕКСНЫЙ АНАЛИЗ АРХИВНЫХ ЛОГОВ")
print("=" * 80)

# Находим все подпапки с логами
archive_folders = [d for d in log_dir.iterdir() if d.is_dir()]
print(f"\nНайдено архивных папок: {len(archive_folders)}")

for archive_folder in archive_folders:
    print(f"\n[Анализирую] {archive_folder.name}")

    # Определяем дату из имени папки или файлов
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", archive_folder.name)
    if not date_match:
        # Пробуем найти дату в файлах
        log_files = list(archive_folder.glob("*.log"))
        if log_files:
            with open(log_files[0], "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
                date_match = patterns["timestamp"].search(first_line)

    date_key = date_match.group(1) if date_match else archive_folder.name

    stats = {
        "date": date_key,
        "positions_opened": 0,
        "positions_closed": 0,
        "positions_profitable": 0,
        "positions_loss": 0,
        "total_pnl": 0.0,
        "total_pnl_percent": 0.0,
        "orders_placed": 0,
        "orders_filled": 0,
        "orders_cancelled": 0,
        "signals_generated": 0,
        "signals_executed": 0,
        "errors": defaultdict(int),
        "warnings": defaultdict(int),
        "errors_51006": 0,
        "timeouts": 0,
        "balances": [],
        "start_time": None,
        "end_time": None,
        "symbols": defaultdict(int),
    }

    log_files = list(archive_folder.glob("*.log"))
    print(f"  Найдено файлов: {len(log_files)}")

    for log_file in log_files:
        if "error" in log_file.name.lower():
            continue

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    # Временные метки
                    time_match = patterns["timestamp"].search(line)
                    if time_match:
                        try:
                            dt = datetime.strptime(
                                time_match.group(1), "%Y-%m-%d %H:%M:%S"
                            )
                            if stats["start_time"] is None or dt < stats["start_time"]:
                                stats["start_time"] = dt
                            if stats["end_time"] is None or dt > stats["end_time"]:
                                stats["end_time"] = dt
                        except:
                            pass

                    # Позиции
                    pos_open = patterns["position_open"].search(line)
                    if pos_open:
                        stats["positions_opened"] += 1
                        symbol = pos_open.group(1)
                        stats["symbols"][symbol] += 1

                    pos_close = patterns["position_close"].search(line)
                    if pos_close:
                        stats["positions_closed"] += 1
                        # Ищем PnL
                        pnl_match = patterns["pnl"].search(line)
                        if pnl_match:
                            pnl = float(pnl_match.group(1))
                            stats["total_pnl"] += pnl
                            if pnl > 0:
                                stats["positions_profitable"] += 1
                            else:
                                stats["positions_loss"] += 1

                        pnl_pct_match = patterns["pnl_percent"].search(line)
                        if pnl_pct_match:
                            pnl_pct = float(pnl_pct_match.group(1))
                            stats["total_pnl_percent"] += pnl_pct

                    # Ордера
                    if patterns["order_placed"].search(line):
                        stats["orders_placed"] += 1

                    if patterns["order_filled"].search(line):
                        stats["orders_filled"] += 1

                    if patterns["order_cancelled"].search(line):
                        stats["orders_cancelled"] += 1

                    # Сигналы
                    if patterns["signal_generated"].search(line):
                        stats["signals_generated"] += 1

                    if patterns["signal_executed"].search(line):
                        stats["signals_executed"] += 1

                    # Баланс
                    equity_match = patterns["equity"].search(line)
                    if equity_match:
                        balance = float(equity_match.group(1))
                        if balance > 100:  # Только реальные балансы
                            stats["balances"].append(balance)

                    # Ошибки
                    if "| ERROR" in line:
                        error_match = patterns["error"].search(line)
                        if error_match:
                            error_msg = error_match.group(1)[:100]
                            stats["errors"][error_msg] += 1

                        if patterns["51006"].search(line):
                            stats["errors_51006"] += 1

                    # Предупреждения
                    if "| WARNING" in line:
                        warn_match = patterns["warning"].search(line)
                        if warn_match:
                            warn_msg = warn_match.group(1)[:100]
                            stats["warnings"][warn_msg] += 1

                    # Таймауты
                    if patterns["timeout"].search(line):
                        stats["timeouts"] += 1

                    if line_num % 50000 == 0:
                        print(f"    Обработано {line_num} строк из {log_file.name}")

        except Exception as e:
            print(f"    [ОШИБКА] Ошибка чтения {log_file.name}: {e}")

    # Анализ файла ошибок отдельно
    error_files = list(archive_folder.glob("*error*.log"))
    for error_file in error_files:
        try:
            with open(error_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "ERROR" in line:
                        error_match = patterns["error"].search(line)
                        if error_match:
                            error_msg = error_match.group(1)[:100]
                            stats["errors"][error_msg] += 1

                        if patterns["51006"].search(line):
                            stats["errors_51006"] += 1
        except:
            pass

    all_stats[date_key] = stats

# Вывод результатов
print("\n" + "=" * 80)
print("ИТОГОВАЯ СТАТИСТИКА ПО ВСЕМ ДНЯМ")
print("=" * 80)

# Общая статистика
total_positions_opened = sum(s["positions_opened"] for s in all_stats.values())
total_positions_closed = sum(s["positions_closed"] for s in all_stats.values())
total_profitable = sum(s["positions_profitable"] for s in all_stats.values())
total_loss = sum(s["positions_loss"] for s in all_stats.values())
total_pnl = sum(s["total_pnl"] for s in all_stats.values())
total_orders_placed = sum(s["orders_placed"] for s in all_stats.values())
total_orders_filled = sum(s["orders_filled"] for s in all_stats.values())
total_errors_51006 = sum(s["errors_51006"] for s in all_stats.values())
total_timeouts = sum(s["timeouts"] for s in all_stats.values())

print(f"\n[ОБЩАЯ СТАТИСТИКА]")
print(f"  Дней проанализировано: {len(all_stats)}")
print(f"  Позиций открыто: {total_positions_opened}")
print(f"  Позиций закрыто: {total_positions_closed}")
print(f"  Прибыльных: {total_profitable}")
print(f"  Убыточных: {total_loss}")
if total_positions_closed > 0:
    win_rate = (total_profitable / total_positions_closed) * 100
    avg_pnl = total_pnl / total_positions_closed
    print(f"  Винрейт: {win_rate:.1f}%")
    print(f"  Общий PnL: ${total_pnl:.2f}")
    print(f"  Средний PnL: ${avg_pnl:.2f}")

print(f"\n[ОРДЕРА]")
print(f"  Размещено: {total_orders_placed}")
print(f"  Исполнено: {total_orders_filled}")
if total_orders_placed > 0:
    effectiveness = (total_orders_filled / total_orders_placed) * 100
    print(f"  Эффективность: {effectiveness:.1f}%")

print(f"\n[ПРОБЛЕМЫ]")
print(f"  Ошибок 51006 (цена вне лимитов): {total_errors_51006}")
print(f"  Таймаутов: {total_timeouts}")

# Детальная статистика по дням
print("\n" + "=" * 80)
print("ДЕТАЛЬНАЯ СТАТИСТИКА ПО ДНЯМ")
print("=" * 80)

for date_key in sorted(all_stats.keys()):
    stats = all_stats[date_key]
    print(f"\n[{date_key}]")

    if stats["start_time"] and stats["end_time"]:
        duration = stats["end_time"] - stats["start_time"]
        print(f"  Время работы: {duration}")

    if stats["balances"]:
        start_balance = stats["balances"][0] if stats["balances"] else 0
        end_balance = stats["balances"][-1] if stats["balances"] else 0
        profit = end_balance - start_balance
        profit_percent = (profit / start_balance * 100) if start_balance > 0 else 0
        print(
            f"  Баланс: ${start_balance:.2f} → ${end_balance:.2f} ({profit:+.2f}, {profit_percent:+.2f}%)"
        )

    print(
        f"  Позиций: открыто={stats['positions_opened']}, закрыто={stats['positions_closed']}"
    )
    if stats["positions_closed"] > 0:
        win_rate = (stats["positions_profitable"] / stats["positions_closed"]) * 100
        print(f"  Винрейт: {win_rate:.1f}%, PnL: ${stats['total_pnl']:.2f}")

    print(
        f"  Ордеров: размещено={stats['orders_placed']}, исполнено={stats['orders_filled']}"
    )
    if stats["orders_placed"] > 0:
        effectiveness = (stats["orders_filled"] / stats["orders_placed"]) * 100
        print(f"  Эффективность: {effectiveness:.1f}%")

    if stats["errors_51006"] > 0:
        print(f"  [ВНИМАНИЕ] Ошибок 51006: {stats['errors_51006']}")

    if stats["timeouts"] > 0:
        print(f"  [ВНИМАНИЕ] Таймаутов: {stats['timeouts']}")

    # Топ ошибок
    if stats["errors"]:
        sorted_errors = sorted(
            stats["errors"].items(), key=lambda x: x[1], reverse=True
        )
        print(f"  Топ ошибок:")
        for i, (msg, count) in enumerate(sorted_errors[:3], 1):
            print(f"    {i}. [{count}x] {msg[:60]}")

# Топ ошибок за все дни
print("\n" + "=" * 80)
print("ТОП ОШИБОК ЗА ВСЕ ДНИ")
print("=" * 80)

all_errors = defaultdict(int)
for stats in all_stats.values():
    for error_msg, count in stats["errors"].items():
        all_errors[error_msg] += count

sorted_all_errors = sorted(all_errors.items(), key=lambda x: x[1], reverse=True)
for i, (msg, count) in enumerate(sorted_all_errors[:15], 1):
    print(f"  {i}. [{count}x] {msg[:70]}")

print("\n" + "=" * 80)
print("АНАЛИЗ ЗАВЕРШЕН")
print("=" * 80)
