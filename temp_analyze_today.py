#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Быстрый анализ логов за сегодня"""

import os
import sys
from pathlib import Path

# Настройка кодировки для Windows
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(
        sys.stdout, "reconfigure"
    ) else None

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime

from logs.analyze_logs import LogAnalyzer


def main():
    print("=" * 80)
    print("📊 АНАЛИЗ ЛОГОВ ЗА 2025-12-18")
    print("=" * 80)
    print()

    analyzer = LogAnalyzer()

    # Ищем логи за сегодня
    date = "2025-12-18"
    log_files = analyzer.find_log_files(date=date)

    if not log_files:
        print(f"❌ Логи за {date} не найдены")
        return

    print(f"✅ Найдено файлов: {len(log_files)}")
    print(f"📁 Файлы:")
    for i, f in enumerate(log_files[:10], 1):
        print(f"   {i}. {f.name}")
    if len(log_files) > 10:
        print(f"   ... и ещё {len(log_files) - 10} файлов")
    print()

    print("🔍 Анализирую логи...")
    stats, parsed_logs = analyzer.analyze_session(log_files)

    print()
    print("=" * 80)
    print("📊 РЕЗУЛЬТАТЫ АНАЛИЗА")
    print("=" * 80)
    print()

    # Временные рамки
    if stats.start_time and stats.end_time:
        duration = stats.end_time - stats.start_time
        duration_str = str(duration).split(".")[0]
        print(f"⏰ ВРЕМЕННЫЕ РАМКИ:")
        print(f"   Начало: {stats.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Конец:  {stats.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Длительность: {duration_str}")
        print()

    # Финансы
    print(f"💰 ФИНАНСОВЫЕ ПОКАЗАТЕЛИ:")
    print(f"   Начальный баланс: ${stats.start_balance:.2f}")
    print(f"   Конечный баланс:  ${stats.end_balance:.2f}")
    profit_sign = "+" if stats.profit >= 0 else ""
    print(
        f"   Прибыль/Убыток:   {profit_sign}${stats.profit:.2f} ({profit_sign}{stats.profit_percent:.2f}%)"
    )
    print()

    # Ордера
    print(f"📈 ОРДЕРА:")
    print(f"   Размещено:     {stats.orders_placed}")
    print(f"   Исполнено:     {stats.orders_filled}")
    print(f"   Отменено:      {stats.orders_cancelled}")
    print(f"   Ошибки:        {stats.orders_failed}")
    print(f"   Эффективность: {stats.order_effectiveness:.1f}%")
    print()

    # Позиции
    print(f"🎯 ПОЗИЦИИ:")
    print(f"   Открыто:       {stats.positions_opened}")
    print(f"   Закрыто:       {stats.positions_closed}")
    print(f"   Прибыльных:    {stats.positions_profitable}")
    print(f"   Убыточных:     {stats.positions_loss}")
    if stats.positions_closed > 0:
        win_rate = (stats.positions_profitable / stats.positions_closed) * 100
        print(f"   Винрейт:       {win_rate:.1f}%")
    print(f"   Общий PnL:     ${stats.total_pnl:.2f}")
    print(f"   Средний PnL:   ${stats.avg_pnl:.2f}")
    print()

    # Ошибки
    print(f"⚠️  ОШИБКИ И ПРЕДУПРЕЖДЕНИЯ:")
    print(f"   Ошибки (ERROR):        {stats.errors_count}")
    print(f"   Предупреждения (WARN): {stats.warnings_count}")
    print(f"   Критические (CRITICAL): {stats.critical_errors}")
    print()

    # Анализ проблем
    print("=" * 80)
    print("🔍 АНАЛИЗ ПРОБЛЕМ")
    print("=" * 80)
    print()

    # Собираем частые ошибки
    error_patterns = {}
    warning_patterns = {}

    for log in parsed_logs:
        msg = log.get("message", "")
        level = log.get("level", "")

        if level == "ERROR":
            # Упрощаем сообщение для группировки
            key = msg[:100] if len(msg) > 100 else msg
            error_patterns[key] = error_patterns.get(key, 0) + 1

        if level == "WARNING":
            key = msg[:100] if len(msg) > 100 else msg
            warning_patterns[key] = warning_patterns.get(key, 0) + 1

    # Топ ошибок
    if error_patterns:
        print("❌ ТОП-10 ОШИБОК:")
        sorted_errors = sorted(error_patterns.items(), key=lambda x: x[1], reverse=True)
        for i, (msg, count) in enumerate(sorted_errors[:10], 1):
            print(f"   {i}. [{count}x] {msg[:150]}")
        print()

    # Топ предупреждений
    if warning_patterns:
        print("⚠️  ТОП-10 ПРЕДУПРЕЖДЕНИЙ:")
        sorted_warnings = sorted(
            warning_patterns.items(), key=lambda x: x[1], reverse=True
        )
        for i, (msg, count) in enumerate(sorted_warnings[:10], 1):
            print(f"   {i}. [{count}x] {msg[:150]}")
        print()

    # Анализ эффективности
    print("=" * 80)
    print("📊 АНАЛИЗ ЭФФЕКТИВНОСТИ")
    print("=" * 80)
    print()

    if stats.orders_placed > 0:
        fill_rate = (stats.orders_filled / stats.orders_placed) * 100
        if fill_rate < 50:
            print("⚠️  ПРОБЛЕМА: Низкая эффективность исполнения ордеров!")
            print(f"   Только {fill_rate:.1f}% ордеров исполнено")
        else:
            print(f"✅ Эффективность исполнения ордеров: {fill_rate:.1f}%")

    if stats.positions_opened > 0:
        close_rate = (stats.positions_closed / stats.positions_opened) * 100
        if close_rate < 80:
            print(f"⚠️  ПРОБЛЕМА: Много незакрытых позиций!")
            print(f"   Закрыто только {close_rate:.1f}% от открытых")
        else:
            print(f"✅ Закрыто {close_rate:.1f}% позиций")

    if stats.positions_closed > 0:
        if stats.positions_profitable == 0:
            print("❌ КРИТИЧНО: Нет прибыльных позиций!")
        elif stats.positions_loss > stats.positions_profitable:
            print("⚠️  ПРОБЛЕМА: Больше убыточных позиций, чем прибыльных")
        else:
            win_rate = (stats.positions_profitable / stats.positions_closed) * 100
            print(f"✅ Винрейт: {win_rate:.1f}%")

    if stats.profit < 0:
        print("❌ КРИТИЧНО: Отрицательная прибыль!")
    elif stats.profit == 0:
        print("⚠️  ПРОБЛЕМА: Нулевая прибыль")
    else:
        print(f"✅ Прибыль: ${stats.profit:.2f}")

    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
