"""
Аудит сигналов и фильтрации торгового бота.

Анализирует:
1. Типы сигналов (MA, RSI, импульсы, BB, MACD)
2. Эффективность фильтров
3. Win rate по типам сигналов
4. Рекомендации по оптимизации
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import statistics

from loguru import logger


class SignalsAndFiltersAuditor:
    """Аудитор сигналов и фильтрации"""

    def __init__(self, trades_file: str):
        """
        Инициализация аудитора

        Args:
            trades_file: Путь к файлу с данными сделок
        """
        self.trades_file = trades_file
        self.trades = []
        self.positions = []  # Группированные позиции
        self.signal_types = {
            "MA": "Moving Average",
            "RSI": "RSI",
            "impulse": "Impulse",
            "BB": "Bollinger Bands",
            "MACD": "MACD",
        }

    def load_trades(self) -> None:
        """Загрузка данных сделок"""
        logger.info(f"📂 Загрузка сделок из {self.trades_file}")
        try:
            with open(self.trades_file, "r", encoding="utf-8") as f:
                self.trades = json.load(f)
            logger.info(f"✅ Загружено {len(self.trades)} сделок")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки сделок: {e}")
            raise

    def group_trades_into_positions(self) -> None:
        """Группировка сделок в позиции"""
        logger.info("📊 Группировка сделок в позиции...")

        # Группируем по symbol, pos_side, order_id
        positions_dict = defaultdict(list)

        for trade in self.trades:
            symbol = trade.get("symbol")
            pos_side = trade.get("pos_side")
            order_id = trade.get("order_id")

            if not symbol or not pos_side or not order_id:
                continue

            key = f"{symbol}_{pos_side}_{order_id}"
            positions_dict[key].append(trade)

        # Сортируем сделки внутри позиции по времени
        for key, trades in positions_dict.items():
            trades.sort(key=lambda x: x.get("timestamp", ""))

        # Формируем позиции
        for key, trades in positions_dict.items():
            if len(trades) < 2:  # Позиция должна иметь минимум 2 сделки (открытие + закрытие)
                continue

            # Первая сделка - открытие, последняя - закрытие
            open_trade = trades[0]
            close_trade = trades[-1]

            # Считаем общий PnL
            total_pnl = sum(
                float(t.get("pnl", 0) or 0) for t in trades if t.get("pnl") is not None
            )

            # Считаем общие комиссии
            total_fees = sum(
                abs(float(t.get("fee", 0) or 0)) for t in trades
            )

            position = {
                "symbol": symbol,
                "pos_side": pos_side,
                "order_id": order_id,
                "open_time": open_trade.get("timestamp"),
                "close_time": close_trade.get("timestamp"),
                "open_price": float(open_trade.get("price", 0)),
                "close_price": float(close_trade.get("price", 0)),
                "size": sum(float(t.get("size", 0)) for t in trades),
                "pnl": total_pnl,
                "fees": total_fees,
                "net_pnl": total_pnl - total_fees,
                "trades_count": len(trades),
                "is_win": total_pnl > 0,
            }

            self.positions.append(position)

        logger.info(f"✅ Сформировано {len(self.positions)} позиций")

    def analyze_signal_types(self) -> Dict[str, Any]:
        """
        Анализ типов сигналов

        Примечание: В данных сделок нет информации о типе сигнала.
        Будем анализировать по косвенным признакам (время, цена, размер).
        """
        logger.info("🔍 Анализ типов сигналов...")

        # Группируем позиции по символам
        by_symbol = defaultdict(list)
        for pos in self.positions:
            by_symbol[pos["symbol"]].append(pos)

        # Анализируем паттерны
        analysis = {
            "total_positions": len(self.positions),
            "by_symbol": {},
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "avg_fees": 0.0,
        }

        wins = sum(1 for p in self.positions if p["is_win"])
        analysis["win_rate"] = (wins / len(self.positions) * 100) if self.positions else 0.0

        if self.positions:
            analysis["avg_pnl"] = statistics.mean([p["pnl"] for p in self.positions])
            analysis["avg_fees"] = statistics.mean([p["fees"] for p in self.positions])

        # Анализ по символам
        for symbol, positions in by_symbol.items():
            symbol_wins = sum(1 for p in positions if p["is_win"])
            symbol_win_rate = (symbol_wins / len(positions) * 100) if positions else 0.0
            symbol_avg_pnl = statistics.mean([p["pnl"] for p in positions]) if positions else 0.0

            analysis["by_symbol"][symbol] = {
                "count": len(positions),
                "win_rate": symbol_win_rate,
                "avg_pnl": symbol_avg_pnl,
                "total_pnl": sum(p["pnl"] for p in positions),
            }

        return analysis

    def analyze_filters_effectiveness(self) -> Dict[str, Any]:
        """
        Анализ эффективности фильтров

        Примечание: В данных сделок нет информации о фильтрах.
        Будем анализировать по косвенным признакам (время удержания, PnL).
        """
        logger.info("🔍 Анализ эффективности фильтров...")

        # Анализируем позиции по времени удержания
        durations = []
        for pos in self.positions:
            try:
                open_time = datetime.fromisoformat(pos["open_time"].replace("Z", "+00:00"))
                close_time = datetime.fromisoformat(pos["close_time"].replace("Z", "+00:00"))
                duration = (close_time - open_time).total_seconds() / 60  # в минутах
                durations.append(duration)
                pos["duration_minutes"] = duration
            except Exception as e:
                logger.debug(f"⚠️ Ошибка расчета длительности для позиции {pos.get('order_id')}: {e}")
                pos["duration_minutes"] = 0

        # Группируем по длительности
        short_positions = [p for p in self.positions if p.get("duration_minutes", 0) < 5]
        medium_positions = [p for p in self.positions if 5 <= p.get("duration_minutes", 0) < 30]
        long_positions = [p for p in self.positions if p.get("duration_minutes", 0) >= 30]

        def calc_stats(positions: List[Dict]) -> Dict[str, float]:
            if not positions:
                return {"count": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total_pnl": 0.0}
            wins = sum(1 for p in positions if p["is_win"])
            return {
                "count": len(positions),
                "win_rate": (wins / len(positions) * 100) if positions else 0.0,
                "avg_pnl": statistics.mean([p["pnl"] for p in positions]) if positions else 0.0,
                "total_pnl": sum(p["pnl"] for p in positions),
            }

        analysis = {
            "by_duration": {
                "short_<5min": calc_stats(short_positions),
                "medium_5-30min": calc_stats(medium_positions),
                "long_>30min": calc_stats(long_positions),
            },
            "avg_duration_minutes": statistics.mean(durations) if durations else 0.0,
        }

        return analysis

    def analyze_entry_quality(self) -> Dict[str, Any]:
        """Анализ качества входов"""
        logger.info("🔍 Анализ качества входов...")

        # Анализируем по направлению (long/short)
        long_positions = [p for p in self.positions if p.get("pos_side", "").lower() == "long"]
        short_positions = [p for p in self.positions if p.get("pos_side", "").lower() == "short"]

        def calc_stats(positions: List[Dict]) -> Dict[str, float]:
            if not positions:
                return {"count": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total_pnl": 0.0}
            wins = sum(1 for p in positions if p["is_win"])
            return {
                "count": len(positions),
                "win_rate": (wins / len(positions) * 100) if positions else 0.0,
                "avg_pnl": statistics.mean([p["pnl"] for p in positions]) if positions else 0.0,
                "total_pnl": sum(p["pnl"] for p in positions),
            }

        analysis = {
            "by_direction": {
                "long": calc_stats(long_positions),
                "short": calc_stats(short_positions),
            },
        }

        return analysis

    def generate_report(self) -> str:
        """Генерация отчета"""
        logger.info("📝 Генерация отчета...")

        signal_analysis = self.analyze_signal_types()
        filters_analysis = self.analyze_filters_effectiveness()
        entry_analysis = self.analyze_entry_quality()

        report = f"""# 🔍 АУДИТ СИГНАЛОВ И ФИЛЬТРАЦИИ

**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Период:** 02-03.12.2025  
**Источник данных:** {self.trades_file}

---

## 📊 ОБЩАЯ СТАТИСТИКА

### Позиции:
- **Всего позиций:** {signal_analysis['total_positions']}
- **Win rate:** {signal_analysis['win_rate']:.2f}%
- **Средний PnL:** ${signal_analysis['avg_pnl']:.2f}
- **Средние комиссии:** ${signal_analysis['avg_fees']:.2f}
- **Средняя длительность:** {filters_analysis['avg_duration_minutes']:.1f} минут

---

## 📈 АНАЛИЗ ПО СИМВОЛАМ

"""

        # Сортируем символы по количеству позиций
        sorted_symbols = sorted(
            signal_analysis["by_symbol"].items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )

        for symbol, stats in sorted_symbols:
            report += f"""
### {symbol}
- **Позиций:** {stats['count']}
- **Win rate:** {stats['win_rate']:.2f}%
- **Средний PnL:** ${stats['avg_pnl']:.2f}
- **Общий PnL:** ${stats['total_pnl']:.2f}
"""

        report += f"""
---

## ⏱️ АНАЛИЗ ПО ДЛИТЕЛЬНОСТИ

### Короткие позиции (< 5 минут)
- **Позиций:** {filters_analysis['by_duration']['short_<5min']['count']}
- **Win rate:** {filters_analysis['by_duration']['short_<5min']['win_rate']:.2f}%
- **Средний PnL:** ${filters_analysis['by_duration']['short_<5min']['avg_pnl']:.2f}
- **Общий PnL:** ${filters_analysis['by_duration']['short_<5min']['total_pnl']:.2f}

### Средние позиции (5-30 минут)
- **Позиций:** {filters_analysis['by_duration']['medium_5-30min']['count']}
- **Win rate:** {filters_analysis['by_duration']['medium_5-30min']['win_rate']:.2f}%
- **Средний PnL:** ${filters_analysis['by_duration']['medium_5-30min']['avg_pnl']:.2f}
- **Общий PnL:** ${filters_analysis['by_duration']['medium_5-30min']['total_pnl']:.2f}

### Длинные позиции (> 30 минут)
- **Позиций:** {filters_analysis['by_duration']['long_>30min']['count']}
- **Win rate:** {filters_analysis['by_duration']['long_>30min']['win_rate']:.2f}%
- **Средний PnL:** ${filters_analysis['by_duration']['long_>30min']['avg_pnl']:.2f}
- **Общий PnL:** ${filters_analysis['by_duration']['long_>30min']['total_pnl']:.2f}

---

## 📊 АНАЛИЗ ПО НАПРАВЛЕНИЮ

### LONG позиции
- **Позиций:** {entry_analysis['by_direction']['long']['count']}
- **Win rate:** {entry_analysis['by_direction']['long']['win_rate']:.2f}%
- **Средний PnL:** ${entry_analysis['by_direction']['long']['avg_pnl']:.2f}
- **Общий PnL:** ${entry_analysis['by_direction']['long']['total_pnl']:.2f}

### SHORT позиции
- **Позиций:** {entry_analysis['by_direction']['short']['count']}
- **Win rate:** {entry_analysis['by_direction']['short']['win_rate']:.2f}%
- **Средний PnL:** ${entry_analysis['by_direction']['short']['avg_pnl']:.2f}
- **Общий PnL:** ${entry_analysis['by_direction']['short']['total_pnl']:.2f}

---

## ⚠️ ОГРАНИЧЕНИЯ АНАЛИЗА

1. **Нет данных о типах сигналов** - в данных сделок нет информации о том, какой тип сигнала (MA, RSI, импульс) привел к открытию позиции
2. **Нет данных о фильтрах** - нет информации о том, какие фильтры были применены и какие отфильтровали сигналы
3. **Косвенный анализ** - анализ проводится по косвенным признакам (время, цена, размер)

---

## 🎯 РЕКОМЕНДАЦИИ

### 1. Улучшение логирования сигналов
- ✅ Добавить логирование типа сигнала при открытии позиции
- ✅ Добавить логирование примененных фильтров
- ✅ Сохранять информацию о сигналах в structured logs

### 2. Анализ фильтров
- ✅ Провести анализ эффективности каждого фильтра отдельно
- ✅ Оптимизировать пороги фильтров на основе данных
- ✅ Адаптировать фильтры по режимам рынка

### 3. Улучшение качества входов
- ✅ Анализировать win rate по типам сигналов
- ✅ Улучшить фильтрацию ложных срабатываний
- ✅ Оптимизировать пороги для разных режимов рынка

---

**Следующие шаги:**
1. Добавить логирование сигналов в structured logs
2. Провести анализ с реальными данными о сигналах
3. Оптимизировать фильтры на основе результатов
"""

        return report

    def save_report(self, report: str, output_file: str = "SIGNALS_AND_FILTERS_AUDIT_REPORT.md") -> None:
        """Сохранение отчета"""
        logger.info(f"💾 Сохранение отчета в {output_file}")
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(report)
            logger.info(f"✅ Отчет сохранен: {output_file}")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения отчета: {e}")
            raise


async def main():
    """Основная функция"""
    # Находим файл с данными сделок
    trades_file = "trades_merged_02-03_12_2025_20251204_200821.json"
    
    if not Path(trades_file).exists():
        logger.error(f"❌ Файл {trades_file} не найден!")
        return

    auditor = SignalsAndFiltersAuditor(trades_file)
    
    try:
        # Загрузка данных
        auditor.load_trades()
        
        # Группировка в позиции
        auditor.group_trades_into_positions()
        
        # Генерация отчета
        report = auditor.generate_report()
        
        # Сохранение отчета
        auditor.save_report(report)
        
        logger.info("✅ Аудит завершен успешно!")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при проведении аудита: {e}")
        raise


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

