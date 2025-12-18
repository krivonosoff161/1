# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from logs.analyze_logs import LogAnalyzer

analyzer = LogAnalyzer()
log_files = analyzer.find_log_files(date="2025-12-18")
print(f"Найдено файлов: {len(log_files)}")
stats, parsed_logs = analyzer.analyze_session(log_files)

print("\n" + "=" * 80)
print("СТАТИСТИКА ЗА 2025-12-18")
print("=" * 80)
print(f"Время: {stats.start_time} - {stats.end_time}")
print(f"Баланс: ${stats.start_balance:.2f} -> ${stats.end_balance:.2f}")
print(f"Прибыль: ${stats.profit:.2f} ({stats.profit_percent:+.2f}%)")
print(
    f"Ордера: размещено={stats.orders_placed}, исполнено={stats.orders_filled}, эффективность={stats.order_effectiveness:.1f}%"
)
print(f"Позиции: открыто={stats.positions_opened}, закрыто={stats.positions_closed}")
print(f"Прибыльных: {stats.positions_profitable}, Убыточных: {stats.positions_loss}")
print(f"Общий PnL: ${stats.total_pnl:.2f}")
print(f"Средний PnL: ${stats.avg_pnl:.2f}")
print(f"Ошибки: {stats.errors_count}, Предупреждения: {stats.warnings_count}")
