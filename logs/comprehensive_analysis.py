#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Комплексный анализ всех логов (включая архивы)
"""

import io
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Настройка кодировки для Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent))

try:
    from analyze_logs import LogAnalyzer
except ImportError:
    print("❌ Ошибка: не найден модуль analyze_logs.py")
    sys.exit(1)


def analyze_all_logs():
    """Анализ всех логов за все даты"""
    print("=" * 80)
    print("🔍 КОМПЛЕКСНЫЙ АНАЛИЗ ВСЕХ ЛОГОВ")
    print("=" * 80)

    analyzer = LogAnalyzer()

    # Находим все логи
    futures_dir = Path("logs/futures")
    all_log_files = []

    # 1. Обычные .log файлы
    for log_file in futures_dir.glob("*.log"):
        if log_file.is_file():
            all_log_files.append(log_file)

    # 2. .zip архивы
    for zip_file in futures_dir.glob("*.zip"):
        all_log_files.append(zip_file)

    # 3. Логи в подпапках
    for subdir in futures_dir.iterdir():
        if subdir.is_dir():
            for nested_log in subdir.rglob("*.log"):
                if nested_log.is_file():
                    all_log_files.append(nested_log)

    print(f"\n📁 Найдено файлов логов: {len(all_log_files)}")

    if not all_log_files:
        print("❌ Логи не найдены!")
        return

    # Группируем по датам
    logs_by_date = defaultdict(list)
    for log_file in all_log_files:
        # Извлекаем дату из имени файла
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", log_file.name)
        if date_match:
            date = date_match.group(1)
            logs_by_date[date].append(log_file)
        else:
            # Если дата не найдена, используем дату модификации
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            date = mtime.strftime("%Y-%m-%d")
            logs_by_date[date].append(log_file)

    print(f"\n📅 Найдено уникальных дат: {len(logs_by_date)}")

    # Анализируем каждую дату
    results = {}
    for date in sorted(logs_by_date.keys()):
        print(f"\n{'='*80}")
        print(f"📊 Анализ за {date}")
        print(f"{'='*80}")

        log_files = logs_by_date[date]
        print(f"Файлов для анализа: {len(log_files)}")

        try:
            stats, parsed_logs = analyzer.analyze_session(log_files)
            results[date] = {
                "stats": stats,
                "parsed_logs": parsed_logs,
                "file_count": len(log_files),
            }

            print(f"\n✅ Результаты за {date}:")
            print(f"   Время: {stats.start_time} - {stats.end_time}")
            print(f"   Длительность: {stats.duration}")
            print(f"   Баланс: ${stats.start_balance:.2f} → ${stats.end_balance:.2f}")
            print(f"   Прибыль: ${stats.profit:.2f} ({stats.profit_percent:+.2f}%)")
            print(
                f"   Ордера: размещено={stats.orders_placed}, исполнено={stats.orders_filled}, эффективность={stats.order_effectiveness:.1f}%"
            )
            print(
                f"   Позиции: открыто={stats.positions_opened}, закрыто={stats.positions_closed}"
            )
            print(
                f"   PnL: ${stats.total_pnl:.2f} (прибыльных={stats.positions_profitable}, убыточных={stats.positions_loss})"
            )
            print(
                f"   Ошибки: ERROR={stats.errors_count}, WARNING={stats.warnings_count}, CRITICAL={stats.critical_errors}"
            )

        except Exception as e:
            print(f"❌ Ошибка при анализе {date}: {e}")
            import traceback

            traceback.print_exc()

    # Общая статистика
    print(f"\n{'='*80}")
    print("📈 ОБЩАЯ СТАТИСТИКА ПО ВСЕМ ДАТАМ")
    print(f"{'='*80}")

    total_profit = sum(r["stats"].profit for r in results.values())
    total_orders_placed = sum(r["stats"].orders_placed for r in results.values())
    total_orders_filled = sum(r["stats"].orders_filled for r in results.values())
    total_positions_opened = sum(r["stats"].positions_opened for r in results.values())
    total_positions_closed = sum(r["stats"].positions_closed for r in results.values())
    total_errors = sum(r["stats"].errors_count for r in results.values())
    total_warnings = sum(r["stats"].warnings_count for r in results.values())
    total_pnl = sum(r["stats"].total_pnl for r in results.values())

    print(f"\n💰 Финансы:")
    print(f"   Общая прибыль: ${total_profit:.2f}")
    print(f"   Общий PnL позиций: ${total_pnl:.2f}")

    print(f"\n📈 Ордера:")
    print(f"   Всего размещено: {total_orders_placed}")
    print(f"   Всего исполнено: {total_orders_filled}")
    if total_orders_placed > 0:
        total_effectiveness = (total_orders_filled / total_orders_placed) * 100
        print(f"   Общая эффективность: {total_effectiveness:.1f}%")

    print(f"\n🎯 Позиции:")
    print(f"   Всего открыто: {total_positions_opened}")
    print(f"   Всего закрыто: {total_positions_closed}")
    if total_positions_closed > 0:
        profitable = sum(r["stats"].positions_profitable for r in results.values())
        loss = sum(r["stats"].positions_loss for r in results.values())
        print(f"   Прибыльных: {profitable}, Убыточных: {loss}")
        win_rate = (profitable / total_positions_closed) * 100
        print(f"   Винрейт: {win_rate:.1f}%")

    print(f"\n⚠️ Ошибки:")
    print(f"   Всего ошибок (ERROR): {total_errors}")
    print(f"   Всего предупреждений (WARNING): {total_warnings}")

    # Анализ проблем
    print(f"\n{'='*80}")
    print("🔍 АНАЛИЗ ПРОБЛЕМ")
    print(f"{'='*80}")

    # Поиск повторяющихся ошибок
    all_messages = []
    for date, result in results.items():
        for log in result["parsed_logs"]:
            if log["level"] in ["ERROR", "WARNING"]:
                all_messages.append(log["message"])

    # Топ ошибок
    error_counter = Counter(all_messages)
    print(f"\n🔴 Топ-10 самых частых ошибок/предупреждений:")
    for msg, count in error_counter.most_common(10):
        print(f"   {count:4d}x: {msg[:100]}")

    # Анализ по датам
    print(f"\n{'='*80}")
    print("📊 СРАВНЕНИЕ ПО ДАТАМ")
    print(f"{'='*80}")

    print(
        f"\n{'Дата':<12} {'Прибыль':<12} {'Ордера':<20} {'Позиции':<20} {'Ошибки':<15}"
    )
    print("-" * 80)
    for date in sorted(results.keys()):
        stats = results[date]["stats"]
        orders_str = f"{stats.orders_placed}/{stats.orders_filled} ({stats.order_effectiveness:.0f}%)"
        positions_str = f"{stats.positions_opened}/{stats.positions_closed}"
        errors_str = f"E:{stats.errors_count} W:{stats.warnings_count}"
        print(
            f"{date:<12} ${stats.profit:>10.2f} {orders_str:<20} {positions_str:<20} {errors_str:<15}"
        )

    # Сохранение отчета
    report_file = Path("logs/COMPREHENSIVE_ANALYSIS_REPORT.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# 🔍 КОМПЛЕКСНЫЙ АНАЛИЗ ВСЕХ ЛОГОВ\n\n")
        f.write(f"**Дата анализа:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Всего файлов проанализировано:** {len(all_log_files)}\n")
        f.write(f"**Всего уникальных дат:** {len(logs_by_date)}\n\n")

        f.write("## 📊 ОБЩАЯ СТАТИСТИКА\n\n")
        f.write(f"- **Общая прибыль:** ${total_profit:.2f}\n")
        f.write(f"- **Общий PnL позиций:** ${total_pnl:.2f}\n")
        f.write(f"- **Всего ордеров размещено:** {total_orders_placed}\n")
        f.write(f"- **Всего ордеров исполнено:** {total_orders_filled}\n")
        if total_orders_placed > 0:
            f.write(f"- **Общая эффективность ордеров:** {total_effectiveness:.1f}%\n")
        f.write(f"- **Всего позиций открыто:** {total_positions_opened}\n")
        f.write(f"- **Всего позиций закрыто:** {total_positions_closed}\n")
        f.write(f"- **Всего ошибок (ERROR):** {total_errors}\n")
        f.write(f"- **Всего предупреждений (WARNING):** {total_warnings}\n\n")

        f.write("## 📅 ДЕТАЛЬНАЯ СТАТИСТИКА ПО ДАТАМ\n\n")
        for date in sorted(results.keys()):
            stats = results[date]["stats"]
            f.write(f"### {date}\n\n")
            f.write(f"- **Время:** {stats.start_time} - {stats.end_time}\n")
            f.write(f"- **Длительность:** {stats.duration}\n")
            f.write(
                f"- **Баланс:** ${stats.start_balance:.2f} → ${stats.end_balance:.2f}\n"
            )
            f.write(
                f"- **Прибыль:** ${stats.profit:.2f} ({stats.profit_percent:+.2f}%)\n"
            )
            f.write(
                f"- **Ордера:** размещено={stats.orders_placed}, исполнено={stats.orders_filled}, эффективность={stats.order_effectiveness:.1f}%\n"
            )
            f.write(
                f"- **Позиции:** открыто={stats.positions_opened}, закрыто={stats.positions_closed}\n"
            )
            f.write(
                f"- **PnL:** ${stats.total_pnl:.2f} (прибыльных={stats.positions_profitable}, убыточных={stats.positions_loss})\n"
            )
            f.write(
                f"- **Ошибки:** ERROR={stats.errors_count}, WARNING={stats.warnings_count}, CRITICAL={stats.critical_errors}\n\n"
            )

        f.write("## 🔴 ТОП ПРОБЛЕМ\n\n")
        f.write("### Топ-20 самых частых ошибок/предупреждений:\n\n")
        for i, (msg, count) in enumerate(error_counter.most_common(20), 1):
            f.write(f"{i}. **{count}x**: {msg[:200]}\n\n")

    print(f"\n✅ Полный отчет сохранен: {report_file}")
    print(f"\n{'='*80}")
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print(f"{'='*80}")


if __name__ == "__main__":
    analyze_all_logs()
