#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализатор логов торговой активности с ДЕТАЛЬНЫМ логированием фильтров

Этот скрипт анализирует CSV логи, сгенерированные PerformanceTracker, и детально рассказывает:
1. Сколько было сигналов на входе
2. Сколько фильтры отклонили и почему
3. Сколько осталось к исполнению
4. Сколько фактически исполнено
5. Статистику по парам

Использует DATA из CSV файлов:
- all_signals.csv (содержит: symbol, side, price, strength, regime, filters_passed, executed, order_id)
- all_positions.csv (содержит: symbol, side, entry_price, size, status, tp_price, sl_price, pnl)
- all_trades.csv (содержит: symbol, side, entry_price, exit_price, pnl_percent, close_reason)

Обновление от 6 января 2026:
- ✅ Теперь executed=True записывается в CSV при открытии позиции (исправлено в entry_manager.py)
- ✅ Детальное логирование фильтров в signal_generator.py
- ✅ Логирование ATR, SL/TP в order_executor.py
- ✅ Логирование причин закрытия в position_manager.py
"""

import csv
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Добавляем path для импорта src модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from loguru import logger

# ============================================================================
# КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ
# ============================================================================

# Очищаем логи
log_dir = Path(__file__).parent / "logs" / "analysis"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = (
    log_dir / f"analysis_detailed_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
)

logger.remove()
logger.add(
    str(log_file),
    format="<level>{level: <8}</level> | <cyan>{time:HH:mm:ss}</cyan> | {message}",
    level="DEBUG",
    rotation="500 MB",
)
logger.add(
    sys.stderr,
    format="<level>{level: <8}</level> | {message}",
    level="INFO",
)

logger.info("=" * 80)
logger.info("🔍 АНАЛИЗАТОР ЛОГОВ С ДЕТАЛЬНЫМ ЛОГИРОВАНИЕМ ФИЛЬТРОВ")
logger.info(f"Дата анализа: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info("=" * 80)


class DetailedLogAnalyzer:
    """Анализатор логов с учетом детального логирования фильтров"""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir).expanduser().resolve() if base_dir else None
        self.signals_data = []
        self.positions_data = []
        self.trades_data = []
        self.filter_stats = defaultdict(lambda: {"passed": 0, "rejected": 0})
        self.symbol_stats = defaultdict(
            lambda: {
                "signals": 0,
                "executed": 0,
                "orders": 0,
                "closed": 0,
                "wins": 0,
                "losses": 0,
                "pnl": 0.0,
            }
        )

    def find_latest_csv_folder(self) -> Optional[Path]:
        """Найти папку с последними CSV логами"""
        if self.base_dir:
            candidate = self.base_dir
            if candidate.is_file():
                candidate = candidate.parent
            if candidate.exists():
                logger.info(f"✅ Используем указанный путь: {candidate}")
                return candidate
            logger.error(f"❌ Указанный путь не найден: {candidate}")
            return None

        search_roots = [
            Path(__file__).parent / "logs" / "futures" / "archived",
            Path(__file__).parent / "logs",
        ]
        candidates = []
        for root in search_roots:
            if not root.exists():
                continue
            for pattern in ["staging_*", "*_2026-*"]:
                for path_str in glob.glob(str(root / pattern)):
                    path = Path(path_str)
                    if path.is_dir():
                        candidates.append(path)

        candidates = sorted(candidates, reverse=True)
        if not candidates:
            logger.error("❌ Не найдены папки логов в стандартных директориях")
            return None

        latest = candidates[0]
        logger.info(f"✅ Найдена папка логов: {latest}")
        return latest

    def load_csv_file(self, csv_path: Path, file_type: str) -> List[Dict]:
        """Загрузить CSV файл и вернуть список словарей"""
        if not csv_path.exists():
            logger.warning(f"⚠️ Файл {csv_path.name} не найден")
            return []

        data = []
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    logger.warning(f"⚠️ CSV {csv_path.name} пуст или поврежден")
                    return []

                for idx, row in enumerate(reader, 1):
                    try:
                        data.append(row)
                    except Exception as e:
                        logger.debug(f"  Ошибка в строке {idx}: {e}")

            logger.info(f"✅ Загружен {file_type}: {csv_path.name} ({len(data)} строк)")
            return data

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {csv_path.name}: {e}")
            return []

    def load_all_data_csv(
        self, csv_path: Path
    ) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """Fallback для all_data_*.csv: разбирает записи по типу"""
        signals: List[Dict] = []
        positions: List[Dict] = []
        trades: List[Dict] = []

        if not csv_path.exists():
            logger.warning(f"⚠️ Файл {csv_path.name} не найден")
            return signals, positions, trades

        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    logger.warning(f"⚠️ CSV {csv_path.name} пуст или поврежден")
                    return signals, positions, trades

                for idx, row in enumerate(reader, 1):
                    rtype = (row.get("record_type") or row.get("type") or "").lower()
                    if rtype in ["signals", "signal"]:
                        signals.append(row)
                    elif rtype in ["orders", "order", "position_open", "position"]:
                        positions.append(row)
                    elif rtype in ["trades", "trade"]:
                        trades.append(row)
                    else:
                        logger.debug(
                            f"  Неизвестный тип записи ({rtype}) в строке {idx}"
                        )

            logger.info(
                f"✅ all_data fallback: {csv_path.name} → signals={len(signals)}, positions={len(positions)}, trades={len(trades)}"
            )
            return signals, positions, trades
        except Exception as e:
            logger.error(f"❌ Ошибка парсинга {csv_path.name}: {e}")
            return signals, positions, trades

    def analyze_signals(self) -> None:
        """Анализ сигналов"""
        logger.info("\n" + "=" * 80)
        logger.info("📊 АНАЛИЗ СИГНАЛОВ")
        logger.info("=" * 80)

        if not self.signals_data:
            logger.warning("⚠️ Нет данных сигналов для анализа")
            return

        # Общая статистика
        total_signals = len(self.signals_data)
        executed_signals = sum(
            1
            for s in self.signals_data
            if s.get("executed", "0") in ["1", "True", "true"]
        )
        rejected_signals = total_signals - executed_signals

        logger.info(f"\n📈 ОБЩАЯ СТАТИСТИКА СИГНАЛОВ:")
        logger.info(f"  Всего сигналов: {total_signals}")
        logger.info(
            f"  Исполнено: {executed_signals} ({executed_signals/total_signals*100:.1f}%)"
        )
        logger.info(
            f"  Отклонено: {rejected_signals} ({rejected_signals/total_signals*100:.1f}%)"
        )
        logger.info(
            f"  → Коэффициент исполнения: {executed_signals/total_signals*100:.1f}% (целевой ~8-10%)"
        )

        # Статистика по парам
        logger.info(f"\n📍 СИГНАЛЫ ПО ПАРАМ:")
        for symbol in sorted(
            set(s.get("symbol", "UNKNOWN") for s in self.signals_data)
        ):
            symbol_signals = [s for s in self.signals_data if s.get("symbol") == symbol]
            symbol_executed = sum(
                1
                for s in symbol_signals
                if s.get("executed", "0") in ["1", "True", "true"]
            )

            logger.info(
                f"  {symbol:10} : {len(symbol_signals):3} signals → "
                f"{symbol_executed:2} executed ({symbol_executed/len(symbol_signals)*100:5.1f}%)"
            )

            self.symbol_stats[symbol]["signals"] = len(symbol_signals)
            self.symbol_stats[symbol]["executed"] = symbol_executed

        # Анализ фильтров (если есть данные)
        logger.info(f"\n🔧 АНАЛИЗ ФИЛЬТРОВ:")
        logger.info(f"  (Данные собираются из поля filters_passed)")

        for signal in self.signals_data[:50]:  # Анализируем первые 50
            filters = signal.get("filters_passed", "")
            if filters:
                logger.debug(
                    f"  {signal.get('symbol')} "
                    f"(executed={signal.get('executed')}) "
                    f"→ filters: {filters}"
                )

        # Сигналы без исполнения (потенциальные причины)
        logger.info(f"\n⚠️ СИГНАЛЫ БЕЗ ИСПОЛНЕНИЯ (первые 10):")
        rejected = [
            s
            for s in self.signals_data
            if s.get("executed", "0") not in ["1", "True", "true"]
        ]
        for sig in rejected[:10]:
            logger.info(
                f"  {sig.get('symbol')} {sig.get('side')} @ {sig.get('price')} "
                f"(strength={sig.get('strength')}, regime={sig.get('regime')})"
            )

    def analyze_positions(self) -> None:
        """Анализ позиций"""
        logger.info("\n" + "=" * 80)
        logger.info("📊 АНАЛИЗ ПОЗИЦИЙ")
        logger.info("=" * 80)

        if not self.positions_data:
            logger.warning("⚠️ Нет данных позиций для анализа")
            return

        total_positions = len(self.positions_data)
        closed_positions = sum(
            1
            for p in self.positions_data
            if p.get("status", "").lower() in ["closed", "closed_tp", "closed_sl"]
        )

        logger.info(f"\n📈 ОБЩАЯ СТАТИСТИКА ПОЗИЦИЙ:")
        logger.info(f"  Всего позиций: {total_positions}")
        logger.info(
            f"  Закрыто: {closed_positions} ({closed_positions/total_positions*100:.1f}%)"
            if total_positions > 0
            else ""
        )
        logger.info(f"  Открыто: {total_positions - closed_positions}")

        # Статистика по парам
        logger.info(f"\n📍 ПОЗИЦИИ ПО ПАРАМ:")
        for symbol in sorted(
            set(p.get("symbol", "UNKNOWN") for p in self.positions_data)
        ):
            symbol_positions = [
                p for p in self.positions_data if p.get("symbol") == symbol
            ]
            symbol_closed = sum(
                1
                for p in symbol_positions
                if p.get("status", "").lower() in ["closed", "closed_tp", "closed_sl"]
            )

            logger.info(
                f"  {symbol:10} : {len(symbol_positions):2} positions → "
                f"{symbol_closed:2} closed"
            )

            self.symbol_stats[symbol]["orders"] = len(symbol_positions)
            self.symbol_stats[symbol]["closed"] = symbol_closed

    def analyze_trades(self) -> None:
        """Анализ закрытых сделок"""
        logger.info("\n" + "=" * 80)
        logger.info("📊 АНАЛИЗ СДЕЛОК")
        logger.info("=" * 80)

        if not self.trades_data:
            logger.warning("⚠️ Нет данных сделок для анализа")
            return

        total_trades = len(self.trades_data)
        wins = []
        losses = []
        total_pnl = 0.0

        for trade in self.trades_data:
            try:
                pnl = float(trade.get("pnl", 0))
                total_pnl += pnl

                if pnl > 0:
                    wins.append(trade)
                else:
                    losses.append(trade)
            except:
                pass

        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
        loss_rate = (len(losses) / total_trades * 100) if total_trades > 0 else 0

        logger.info(f"\n📈 ОБЩАЯ СТАТИСТИКА СДЕЛОК:")
        logger.info(f"  Всего сделок: {total_trades}")
        logger.info(f"  Выигрыши: {len(wins)} ({win_rate:.1f}%)")
        logger.info(f"  Проигрыши: {len(losses)} ({loss_rate:.1f}%)")
        logger.info(f"  Общий P&L: {total_pnl:.2f} USD")
        logger.info(
            f"  Средний P&L на сделку: {total_pnl/total_trades:.2f} USD"
            if total_trades > 0
            else ""
        )

        # Статистика по парам
        logger.info(f"\n📍 СДЕЛКИ ПО ПАРАМ:")
        symbol_trades = defaultdict(list)
        for trade in self.trades_data:
            symbol = trade.get("symbol", "UNKNOWN")
            symbol_trades[symbol].append(trade)

        for symbol in sorted(symbol_trades.keys()):
            trades = symbol_trades[symbol]
            symbol_pnl = sum(float(t.get("pnl", 0)) for t in trades)
            symbol_wins = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)

            logger.info(
                f"  {symbol:10} : {len(trades):2} trades → "
                f"{symbol_wins:2} wins ({symbol_wins/len(trades)*100:5.1f}%) → "
                f"P&L: {symbol_pnl:+8.2f} USD"
            )

            self.symbol_stats[symbol]["wins"] = symbol_wins
            self.symbol_stats[symbol]["losses"] = len(trades) - symbol_wins
            self.symbol_stats[symbol]["pnl"] = symbol_pnl

    def print_summary(self) -> None:
        """Печать итогового резюме"""
        logger.info("\n" + "=" * 80)
        logger.info("📊 ИТОГОВОЕ РЕЗЮМЕ ПО ПАРАМ")
        logger.info("=" * 80)

        logger.info(
            f"\n{'Пара':<10} | {'Сигналы':<10} | {'Исполнено':<10} | "
            f"{'Позиции':<10} | {'Закрыто':<10} | {'Прибыль':<12} | {'Сделки':<8}"
        )
        logger.info("-" * 90)

        for symbol in sorted(self.symbol_stats.keys()):
            stats = self.symbol_stats[symbol]
            logger.info(
                f"{symbol:<10} | "
                f"{stats['signals']:<10} | "
                f"{stats['executed']:<10} | "
                f"{stats['orders']:<10} | "
                f"{stats['closed']:<10} | "
                f"{stats['pnl']:+11.2f} | "
                f"{stats['wins']+stats['losses']:<8}"
            )

        # Критические вопросы
        logger.info("\n" + "=" * 80)
        logger.info("❓ КРИТИЧЕСКИЕ ВОПРОСЫ ДЛЯ ОТЛАДКИ")
        logger.info("=" * 80)

        total_signals = sum(s["signals"] for s in self.symbol_stats.values())
        total_executed = sum(s["executed"] for s in self.symbol_stats.values())
        total_trades = sum(s["wins"] + s["losses"] for s in self.symbol_stats.values())

        logger.info(f"\n1️⃣ КОНВЕРСИЯ СИГНАЛОВ В ПОЗИЦИИ:")
        logger.info(f"   Сигналов: {total_signals}")
        logger.info(f"   Исполнено: {total_executed}")
        logger.info(
            f"   Коэффициент: {total_executed/total_signals*100:.1f}% (целевой: 8-10%)"
        )

        if total_executed == 0:
            logger.error(f"   ❌ ПРОБЛЕМА: Ни один сигнал не исполнен!")
        elif total_executed > total_signals * 0.5:
            logger.warning(f"   ⚠️ ВНИМАНИЕ: Высокий коэффициент исполнения")
        else:
            logger.info(f"   ✅ Нормальный коэффициент")

        logger.info(f"\n2️⃣ ФИЛЬТРАЦИЯ СИГНАЛОВ:")
        rejected_rate = (
            (1 - total_executed / total_signals) * 100 if total_signals > 0 else 0
        )
        logger.info(f"   Отклонено фильтрами: {rejected_rate:.1f}%")
        logger.info(
            f"   → Нужно проверить детальное логирование фильтров в signal_generator.py"
        )

        logger.info(f"\n3️⃣ КАЧЕСТВО ТРЕЙДОВ:")
        if total_trades > 0:
            win_rate = (
                sum(s["wins"] for s in self.symbol_stats.values()) / total_trades * 100
            )
            logger.info(f"   Win rate: {win_rate:.1f}%")
            if win_rate < 40:
                logger.error(f"   ❌ ПРОБЛЕМА: Win rate слишком низкий!")
            else:
                logger.info(f"   ✅ Приемлемый win rate")

        logger.info(f"\n4️⃣ САМАЯ ПРОБЛЕМНАЯ ПАРА:")
        worst_symbol = min(
            self.symbol_stats.items(), key=lambda x: x[1]["pnl"], default=(None, {})
        )
        if worst_symbol[0]:
            logger.error(
                f"   {worst_symbol[0]}: {worst_symbol[1]['pnl']:+.2f} USD "
                f"(win_rate={worst_symbol[1]['wins']/(worst_symbol[1]['wins']+worst_symbol[1]['losses'])*100:.1f}% if trades else 0)"
            )

    def run(self) -> None:
        """Запустить полный анализ"""
        log_folder = self.find_latest_csv_folder()
        if not log_folder:
            logger.error("❌ Не удалось найти папку логов")
            return

        self.signals_data = self.load_csv_file(
            log_folder / "all_signals.csv", "Сигналы"
        )
        self.positions_data = self.load_csv_file(
            log_folder / "all_positions.csv", "Позиции"
        )
        self.trades_data = self.load_csv_file(log_folder / "all_trades.csv", "Сделки")

        if not self.signals_data and not self.positions_data and not self.trades_data:
            all_data_files = sorted(log_folder.glob("all_data_*.csv"), reverse=True)
            if all_data_files:
                logger.info(
                    f"⚙️ Используем fallback all_data: {all_data_files[0].name}"
                )
                signals, positions, trades = self.load_all_data_csv(all_data_files[0])
                if signals:
                    self.signals_data = signals
                if positions:
                    self.positions_data = positions
                if trades:
                    self.trades_data = trades
            else:
                logger.error("❌ Нет ни отдельных CSV, ни all_data_*.csv")
                return

        self.analyze_signals()
        self.analyze_positions()
        self.analyze_trades()
        self.print_summary()

        logger.info("\n" + "=" * 80)
        logger.info(f"✅ Анализ завершен. Логи сохранены в: {log_file}")
        logger.info("=" * 80)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Detailed futures log analyzer")
    parser.add_argument(
        "--path",
        "-p",
        help="Путь к папке с логами или файлу all_data_*.csv (по умолчанию — последний staging)",
    )
    args = parser.parse_args()

    analyzer = DetailedLogAnalyzer(base_dir=args.path)
    analyzer.run()
