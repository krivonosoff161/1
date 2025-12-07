"""
Аудит адаптивности (режимы рынка)
Проверяет:
- Правильность определения режимов (trending/ranging/choppy)
- Применение параметров по режимам
- Переключение между режимами
- Эффективность адаптивных параметров
"""

import asyncio
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

# Настройка логирования
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
)


class AdaptivityAuditor:
    """Аудитор адаптивности торгового бота"""

    def __init__(self):
        self.exchange_positions_file = Path("exchange_positions.json")
        self.exchange_trades_file = Path("exchange_trades_merged.json")
        self.positions_data = []
        self.trades_data = []

    async def load_data(self):
        """Загрузка данных о позициях и сделках"""
        logger.info("📂 Загрузка данных...\n")

        # Загружаем позиции
        if self.exchange_positions_file.exists():
            with open(self.exchange_positions_file, "r", encoding="utf-8") as f:
                self.positions_data = json.load(f)
            logger.info(f"✅ Загружено позиций: {len(self.positions_data)}\n")
        else:
            logger.warning(f"⚠️ Файл {self.exchange_positions_file} не найден\n")
            return False

        # Загружаем сделки
        if self.exchange_trades_file.exists():
            with open(self.exchange_trades_file, "r", encoding="utf-8") as f:
                self.trades_data = json.load(f)
            logger.info(f"✅ Загружено сделок: {len(self.trades_data)}\n")
        else:
            logger.warning(f"⚠️ Файл {self.exchange_trades_file} не найден\n")

        return True

    def analyze_regime_usage(self) -> Dict:
        """Анализ использования режимов"""
        logger.info("🔍 Анализ использования режимов...\n")

        regime_stats = defaultdict(
            lambda: {
                "count": 0,
                "total_pnl": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "avg_pnl": 0.0,
                "symbols": defaultdict(int),
            }
        )

        for pos in self.positions_data:
            regime = pos.get("regime", "unknown")
            pnl = float(pos.get("pnl", 0))
            symbol = pos.get("symbol", "unknown")

            regime_stats[regime]["count"] += 1
            regime_stats[regime]["total_pnl"] += pnl
            regime_stats[regime]["symbols"][symbol] += 1

            if pnl > 0:
                regime_stats[regime]["win_count"] += 1
            elif pnl < 0:
                regime_stats[regime]["loss_count"] += 1

        # Вычисляем средний PnL
        for regime in regime_stats:
            if regime_stats[regime]["count"] > 0:
                regime_stats[regime]["avg_pnl"] = (
                    regime_stats[regime]["total_pnl"] / regime_stats[regime]["count"]
                )

        return dict(regime_stats)

    def analyze_regime_switches(self) -> Dict:
        """Анализ переключений между режимами"""
        logger.info("🔍 Анализ переключений режимов...\n")

        # Группируем позиции по символам и времени
        positions_by_symbol = defaultdict(list)
        for pos in self.positions_data:
            symbol = pos.get("symbol", "unknown")
            entry_time = pos.get("entry_time")
            if entry_time:
                positions_by_symbol[symbol].append(pos)

        # Сортируем по времени
        for symbol in positions_by_symbol:
            positions_by_symbol[symbol].sort(
                key=lambda x: x.get("entry_time", ""), reverse=False
            )

        switches = []
        for symbol, positions in positions_by_symbol.items():
            prev_regime = None
            for pos in positions:
                current_regime = pos.get("regime", "unknown")
                if prev_regime and prev_regime != current_regime:
                    switches.append(
                        {
                            "symbol": symbol,
                            "from": prev_regime,
                            "to": current_regime,
                            "time": pos.get("entry_time"),
                        }
                    )
                prev_regime = current_regime

        return {
            "total_switches": len(switches),
            "switches": switches,
        }

    def analyze_regime_parameters(self) -> Dict:
        """Анализ применения параметров по режимам"""
        logger.info("🔍 Анализ применения параметров...\n")

        # Проверяем наличие режима в позициях
        positions_with_regime = sum(
            1 for pos in self.positions_data if pos.get("regime")
        )
        positions_without_regime = len(self.positions_data) - positions_with_regime

        # Анализируем параметры по режимам
        regime_params = defaultdict(
            lambda: {
                "tp_percent": [],
                "sl_percent": [],
                "holding_time": [],
            }
        )

        for pos in self.positions_data:
            regime = pos.get("regime")
            if not regime:
                continue

            # Пытаемся извлечь параметры из позиции
            # (если они сохраняются)
            tp = pos.get("tp_percent")
            sl = pos.get("sl_percent")
            holding = pos.get("holding_minutes")

            if tp:
                regime_params[regime]["tp_percent"].append(float(tp))
            if sl:
                regime_params[regime]["sl_percent"].append(float(sl))
            if holding:
                regime_params[regime]["holding_time"].append(float(holding))

        # Вычисляем средние значения
        for regime in regime_params:
            for param in regime_params[regime]:
                values = regime_params[regime][param]
                if values:
                    regime_params[regime][f"avg_{param}"] = sum(values) / len(values)
                    regime_params[regime][f"min_{param}"] = min(values)
                    regime_params[regime][f"max_{param}"] = max(values)

        return {
            "positions_with_regime": positions_with_regime,
            "positions_without_regime": positions_without_regime,
            "regime_params": dict(regime_params),
        }

    def analyze_regime_effectiveness(self) -> Dict:
        """Анализ эффективности режимов"""
        logger.info("🔍 Анализ эффективности режимов...\n")

        effectiveness = {}

        for pos in self.positions_data:
            regime = pos.get("regime", "unknown")
            pnl = float(pos.get("pnl", 0))
            symbol = pos.get("symbol", "unknown")

            if regime not in effectiveness:
                effectiveness[regime] = {
                    "total_pnl": 0.0,
                    "count": 0,
                    "win_rate": 0.0,
                    "avg_pnl": 0.0,
                    "symbols": defaultdict(lambda: {"pnl": 0.0, "count": 0}),
                }

            effectiveness[regime]["total_pnl"] += pnl
            effectiveness[regime]["count"] += 1
            effectiveness[regime]["symbols"][symbol]["pnl"] += pnl
            effectiveness[regime]["symbols"][symbol]["count"] += 1

        # Вычисляем win rate и средний PnL
        for regime in effectiveness:
            wins = sum(
                1
                for pos in self.positions_data
                if pos.get("regime") == regime and float(pos.get("pnl", 0)) > 0
            )
            total = effectiveness[regime]["count"]
            effectiveness[regime]["win_rate"] = (wins / total * 100) if total > 0 else 0
            effectiveness[regime]["avg_pnl"] = (
                effectiveness[regime]["total_pnl"] / total if total > 0 else 0
            )

        return effectiveness

    def generate_report(self, stats: Dict) -> str:
        """Генерация отчета"""
        report = []
        report.append("# 🔍 АУДИТ АДАПТИВНОСТИ (РЕЖИМЫ РЫНКА)\n")
        report.append(f"**Дата:** {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        report.append("---\n\n")

        # Статистика использования режимов
        report.append("## 📊 СТАТИСТИКА ИСПОЛЬЗОВАНИЯ РЕЖИМОВ\n\n")
        regime_usage = stats.get("regime_usage", {})
        if regime_usage:
            report.append("| Режим | Позиций | Win Rate | Средний PnL | Общий PnL |\n")
            report.append("|-------|---------|----------|-------------|----------|\n")
            for regime, data in sorted(regime_usage.items()):
                win_rate = (
                    (data["win_count"] / data["count"] * 100)
                    if data["count"] > 0
                    else 0
                )
                report.append(
                    f"| {regime.upper()} | {data['count']} | {win_rate:.1f}% | "
                    f"${data['avg_pnl']:.2f} | ${data['total_pnl']:.2f} |\n"
                )
        else:
            report.append("⚠️ Нет данных о режимах в позициях\n\n")

        # Переключения режимов
        report.append("## 🔄 ПЕРЕКЛЮЧЕНИЯ МЕЖДУ РЕЖИМАМИ\n\n")
        switches = stats.get("regime_switches", {})
        report.append(
            f"**Всего переключений:** {switches.get('total_switches', 0)}\n\n"
        )
        if switches.get("switches"):
            report.append("**Примеры переключений:**\n")
            for switch in switches["switches"][:10]:
                report.append(
                    f"- {switch['symbol']}: {switch['from']} → {switch['to']} "
                    f"({switch.get('time', 'N/A')})\n"
                )

        # Применение параметров
        report.append("\n## ⚙️ ПРИМЕНЕНИЕ ПАРАМЕТРОВ ПО РЕЖИМАМ\n\n")
        params = stats.get("regime_parameters", {})
        report.append(
            f"**Позиций с режимом:** {params.get('positions_with_regime', 0)}\n"
        )
        report.append(
            f"**Позиций без режима:** {params.get('positions_without_regime', 0)}\n\n"
        )

        # Эффективность режимов
        report.append("## 📈 ЭФФЕКТИВНОСТЬ РЕЖИМОВ\n\n")
        effectiveness = stats.get("regime_effectiveness", {})
        if effectiveness:
            report.append("| Режим | Позиций | Win Rate | Средний PnL | Общий PnL |\n")
            report.append("|-------|---------|----------|-------------|----------|\n")
            for regime, data in sorted(effectiveness.items()):
                report.append(
                    f"| {regime.upper()} | {data['count']} | {data['win_rate']:.1f}% | "
                    f"${data['avg_pnl']:.2f} | ${data['total_pnl']:.2f} |\n"
                )

        # Проблемы
        report.append("\n## ⚠️ НАЙДЕННЫЕ ПРОБЛЕМЫ\n\n")
        problems = []

        if params.get("positions_without_regime", 0) > 0:
            pct = (
                params["positions_without_regime"] / len(self.positions_data) * 100
                if self.positions_data
                else 0
            )
            problems.append(
                f"1. **{pct:.1f}% позиций без режима** - режим не сохраняется в позициях"
            )

        if not regime_usage:
            problems.append(
                "2. **Нет данных о режимах** - режимы не сохраняются в позициях"
            )

        if problems:
            for problem in problems:
                report.append(f"- {problem}\n")
        else:
            report.append("✅ Критических проблем не найдено\n")

        # Рекомендации
        report.append("\n## 🎯 РЕКОМЕНДАЦИИ\n\n")
        recommendations = []

        if params.get("positions_without_regime", 0) > 0:
            recommendations.append(
                "1. **Сохранять режим в позициях** - добавить сохранение режима при открытии позиции"
            )

        if not regime_usage:
            recommendations.append(
                "2. **Логировать режимы** - добавить логирование режима при открытии позиции"
            )

        if recommendations:
            for rec in recommendations:
                report.append(f"- {rec}\n")
        else:
            report.append("✅ Все рекомендации выполнены\n")

        return "".join(report)

    async def run_audit(self):
        """Запуск аудита"""
        logger.info("🚀 НАЧАЛО АУДИТА АДАПТИВНОСТИ\n")
        logger.info("=" * 60 + "\n\n")

        # Загрузка данных
        if not await self.load_data():
            logger.error("❌ Не удалось загрузить данные\n")
            return

        # Анализ
        stats = {
            "regime_usage": self.analyze_regime_usage(),
            "regime_switches": self.analyze_regime_switches(),
            "regime_parameters": self.analyze_regime_parameters(),
            "regime_effectiveness": self.analyze_regime_effectiveness(),
        }

        # Генерация отчета
        report = self.generate_report(stats)

        # Сохранение отчета
        report_file = Path("ADAPTIVITY_AUDIT_REPORT.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        logger.info("\n" + "=" * 60 + "\n")
        logger.info("✅ АУДИТ ЗАВЕРШЕН\n")
        logger.info(f"📄 Отчет сохранен: {report_file}\n")

        # Вывод краткой статистики
        logger.info("\n📊 КРАТКАЯ СТАТИСТИКА:\n")
        regime_usage = stats.get("regime_usage", {})
        if regime_usage:
            for regime, data in sorted(regime_usage.items()):
                win_rate = (
                    (data["win_count"] / data["count"] * 100)
                    if data["count"] > 0
                    else 0
                )
                logger.info(
                    f"  {regime.upper()}: {data['count']} позиций, "
                    f"win rate {win_rate:.1f}%, средний PnL ${data['avg_pnl']:.2f}\n"
                )


async def main():
    auditor = AdaptivityAuditor()
    await auditor.run_audit()


if __name__ == "__main__":
    asyncio.run(main())
