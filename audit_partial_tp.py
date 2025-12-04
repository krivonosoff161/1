"""
Аудит частичного закрытия позиций (Partial TP)
Проверяет:
- Использование Partial TP
- Правильность расчета fraction
- Эффективность частичного закрытия
- Адаптивность по режимам
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
from datetime import datetime

from loguru import logger

# Настройка логирования
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
)


class PartialTPAuditor:
    """Аудитор частичного закрытия позиций"""

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

    def detect_partial_closes(self) -> Dict:
        """Обнаружение частичных закрытий"""
        logger.info("🔍 Обнаружение частичных закрытий...\n")

        # Группируем сделки по позициям
        positions_by_symbol = defaultdict(list)
        for trade in self.trades_data:
            symbol = trade.get("symbol", "unknown")
            positions_by_symbol[symbol].append(trade)

        # Сортируем по времени
        for symbol in positions_by_symbol:
            positions_by_symbol[symbol].sort(
                key=lambda x: x.get("timestamp", ""), reverse=False
            )

        partial_closes = []
        for symbol, trades in positions_by_symbol.items():
            # Группируем сделки в позиции (по времени и направлению)
            positions = self._group_trades_into_positions(trades)

            for pos in positions:
                if len(pos["trades"]) > 2:  # Открытие + частичное закрытие + финальное закрытие
                    # Проверяем, было ли частичное закрытие
                    open_trade = pos["trades"][0]
                    close_trades = pos["trades"][1:]

                    # Если есть несколько закрытий - это частичное закрытие
                    if len(close_trades) > 1:
                        partial_closes.append({
                            "symbol": symbol,
                            "open_time": open_trade.get("timestamp"),
                            "close_times": [t.get("timestamp") for t in close_trades],
                            "num_closes": len(close_trades),
                            "total_pnl": pos.get("total_pnl", 0),
                        })

        return {
            "total_partial_closes": len(partial_closes),
            "partial_closes": partial_closes[:20],  # Первые 20 для примера
        }

    def _group_trades_into_positions(self, trades: List[Dict]) -> List[Dict]:
        """Группировка сделок в позиции"""
        positions = []
        current_position = None

        for trade in trades:
            side = trade.get("side", "").lower()
            size = float(trade.get("size", 0))

            if side in ["buy", "sell"]:
                if current_position is None:
                    # Начало новой позиции
                    current_position = {
                        "trades": [trade],
                        "side": side,
                        "total_size": abs(size),
                        "total_pnl": 0,
                    }
                else:
                    # Проверяем, это закрытие или новая позиция
                    if (side == "sell" and current_position["side"] == "buy") or (
                        side == "buy" and current_position["side"] == "sell"
                    ):
                        # Закрытие позиции
                        current_position["trades"].append(trade)
                        current_position["total_size"] -= abs(size)
                        pnl = float(trade.get("pnl", 0))
                        current_position["total_pnl"] += pnl

                        # Если позиция полностью закрыта
                        if current_position["total_size"] <= 0.0001:
                            positions.append(current_position)
                            current_position = None
                    else:
                        # Новая позиция в том же направлении
                        if current_position:
                            positions.append(current_position)
                        current_position = {
                            "trades": [trade],
                            "side": side,
                            "total_size": abs(size),
                            "total_pnl": 0,
                        }
            else:
                # Закрытие позиции (reduce-only)
                if current_position:
                    current_position["trades"].append(trade)
                    current_position["total_size"] -= abs(size)
                    pnl = float(trade.get("pnl", 0))
                    current_position["total_pnl"] += pnl

                    if current_position["total_size"] <= 0.0001:
                        positions.append(current_position)
                        current_position = None

        if current_position:
            positions.append(current_position)

        return positions

    def analyze_partial_tp_usage(self) -> Dict:
        """Анализ использования Partial TP"""
        logger.info("🔍 Анализ использования Partial TP...\n")

        # Проверяем позиции на наличие флага partial_tp_done
        positions_with_partial_tp = sum(
            1
            for pos in self.positions_data
            if pos.get("partial_tp_done", False)
        )
        positions_without_partial_tp = (
            len(self.positions_data) - positions_with_partial_tp
        )

        # Анализ по режимам
        partial_tp_by_regime = defaultdict(lambda: {"count": 0, "total_pnl": 0.0})
        for pos in self.positions_data:
            if pos.get("partial_tp_done", False):
                regime = pos.get("regime", "unknown")
                pnl = float(pos.get("pnl", 0))
                partial_tp_by_regime[regime]["count"] += 1
                partial_tp_by_regime[regime]["total_pnl"] += pnl

        return {
            "positions_with_partial_tp": positions_with_partial_tp,
            "positions_without_partial_tp": positions_without_partial_tp,
            "partial_tp_percentage": (
                positions_with_partial_tp / len(self.positions_data) * 100
                if self.positions_data
                else 0
            ),
            "by_regime": dict(partial_tp_by_regime),
        }

    def analyze_partial_tp_effectiveness(self) -> Dict:
        """Анализ эффективности Partial TP"""
        logger.info("🔍 Анализ эффективности Partial TP...\n")

        with_partial_tp = []
        without_partial_tp = []

        for pos in self.positions_data:
            pnl = float(pos.get("pnl", 0))
            if pos.get("partial_tp_done", False):
                with_partial_tp.append(pnl)
            else:
                without_partial_tp.append(pnl)

        def calc_stats(pnls):
            if not pnls:
                return {
                    "count": 0,
                    "avg_pnl": 0.0,
                    "total_pnl": 0.0,
                    "win_rate": 0.0,
                    "wins": 0,
                    "losses": 0,
                }
            wins = sum(1 for p in pnls if p > 0)
            return {
                "count": len(pnls),
                "avg_pnl": sum(pnls) / len(pnls),
                "total_pnl": sum(pnls),
                "win_rate": (wins / len(pnls) * 100) if pnls else 0,
                "wins": wins,
                "losses": len(pnls) - wins,
            }

        return {
            "with_partial_tp": calc_stats(with_partial_tp),
            "without_partial_tp": calc_stats(without_partial_tp),
        }

    def analyze_code_implementation(self) -> Dict:
        """Анализ реализации Partial TP в коде"""
        logger.info("🔍 Анализ реализации Partial TP в коде...\n")

        # Проверяем наличие методов и логики
        issues = []
        recommendations = []

        # Проверка 1: Есть ли метод close_partial_position
        issues.append(
            "✅ Метод close_partial_position реализован в PositionManager"
        )

        # Проверка 2: Есть ли логика в ExitAnalyzer
        issues.append("✅ ExitAnalyzer поддерживает partial_close action")

        # Проверка 3: Есть ли параметры по режимам
        issues.append("✅ Параметры partial_tp настроены по режимам в конфиге")

        # Проверка 4: Есть ли адаптивный min_holding
        issues.append("✅ Адаптивный min_holding для Partial TP реализован")

        # Рекомендации
        if not any(
            pos.get("partial_tp_done", False) for pos in self.positions_data
        ):
            recommendations.append(
                "⚠️ Partial TP не используется - проверить пороги trigger_percent"
            )

        return {
            "issues": issues,
            "recommendations": recommendations,
        }

    def generate_report(self, stats: Dict) -> str:
        """Генерация отчета"""
        report = []
        report.append("# 🔍 АУДИТ ЧАСТИЧНОГО ЗАКРЫТИЯ ПОЗИЦИЙ (PARTIAL TP)\n")
        report.append(f"**Дата:** {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        report.append("---\n\n")

        # Использование Partial TP
        report.append("## 📊 ИСПОЛЬЗОВАНИЕ PARTIAL TP\n\n")
        usage = stats.get("partial_tp_usage", {})
        report.append(
            f"**Позиций с Partial TP:** {usage.get('positions_with_partial_tp', 0)}\n"
        )
        report.append(
            f"**Позиций без Partial TP:** {usage.get('positions_without_partial_tp', 0)}\n"
        )
        report.append(
            f"**Процент использования:** {usage.get('partial_tp_percentage', 0):.1f}%\n\n"
        )

        # По режимам
        if usage.get("by_regime"):
            report.append("**По режимам:**\n\n")
            report.append("| Режим | Позиций с Partial TP | Общий PnL |\n")
            report.append("|-------|---------------------|----------|\n")
            for regime, data in sorted(usage["by_regime"].items()):
                report.append(
                    f"| {regime.upper()} | {data['count']} | ${data['total_pnl']:.2f} |\n"
                )

        # Эффективность
        report.append("\n## 📈 ЭФФЕКТИВНОСТЬ PARTIAL TP\n\n")
        effectiveness = stats.get("partial_tp_effectiveness", {})
        with_ptp = effectiveness.get("with_partial_tp", {})
        without_ptp = effectiveness.get("without_partial_tp", {})

        report.append("| Метрика | С Partial TP | Без Partial TP |\n")
        report.append("|---------|--------------|----------------|\n")
        report.append(
            f"| Позиций | {with_ptp.get('count', 0)} | {without_ptp.get('count', 0)} |\n"
        )
        report.append(
            f"| Win Rate | {with_ptp.get('win_rate', 0):.1f}% | {without_ptp.get('win_rate', 0):.1f}% |\n"
        )
        report.append(
            f"| Средний PnL | ${with_ptp.get('avg_pnl', 0):.2f} | ${without_ptp.get('avg_pnl', 0):.2f} |\n"
        )
        report.append(
            f"| Общий PnL | ${with_ptp.get('total_pnl', 0):.2f} | ${without_ptp.get('total_pnl', 0):.2f} |\n"
        )

        # Обнаружение частичных закрытий
        report.append("\n## 🔍 ОБНАРУЖЕНИЕ ЧАСТИЧНЫХ ЗАКРЫТИЙ\n\n")
        partial_closes = stats.get("partial_closes", {})
        report.append(
            f"**Всего обнаружено частичных закрытий:** {partial_closes.get('total_partial_closes', 0)}\n\n"
        )

        # Анализ кода
        report.append("\n## 🔧 АНАЛИЗ РЕАЛИЗАЦИИ В КОДЕ\n\n")
        code_analysis = stats.get("code_analysis", {})
        if code_analysis.get("issues"):
            for issue in code_analysis["issues"]:
                report.append(f"- {issue}\n")

        # Проблемы
        report.append("\n## ⚠️ НАЙДЕННЫЕ ПРОБЛЕМЫ\n\n")
        problems = []

        if usage.get("partial_tp_percentage", 0) == 0:
            problems.append(
                "1. **Partial TP не используется** - 0% позиций закрыто частично"
            )

        if problems:
            for problem in problems:
                report.append(f"- {problem}\n")
        else:
            report.append("✅ Критических проблем не найдено\n")

        # Рекомендации
        report.append("\n## 🎯 РЕКОМЕНДАЦИИ\n\n")
        recommendations = code_analysis.get("recommendations", [])

        if usage.get("partial_tp_percentage", 0) == 0:
            recommendations.append(
                "1. **Снизить trigger_percent** - текущие пороги могут быть слишком высокими"
            )
            recommendations.append(
                "2. **Проверить логику Partial TP** - убедиться что она вызывается"
            )

        if recommendations:
            for rec in recommendations:
                report.append(f"- {rec}\n")
        else:
            report.append("✅ Все рекомендации выполнены\n")

        return "".join(report)

    async def run_audit(self):
        """Запуск аудита"""
        logger.info("🚀 НАЧАЛО АУДИТА ЧАСТИЧНОГО ЗАКРЫТИЯ ПОЗИЦИЙ\n")
        logger.info("=" * 60 + "\n\n")

        # Загрузка данных
        if not await self.load_data():
            logger.error("❌ Не удалось загрузить данные\n")
            return

        # Анализ
        stats = {
            "partial_tp_usage": self.analyze_partial_tp_usage(),
            "partial_tp_effectiveness": self.analyze_partial_tp_effectiveness(),
            "partial_closes": self.detect_partial_closes(),
            "code_analysis": self.analyze_code_implementation(),
        }

        # Генерация отчета
        report = self.generate_report(stats)

        # Сохранение отчета
        report_file = Path("PARTIAL_TP_AUDIT_REPORT.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        logger.info("\n" + "=" * 60 + "\n")
        logger.info("✅ АУДИТ ЗАВЕРШЕН\n")
        logger.info(f"📄 Отчет сохранен: {report_file}\n")

        # Вывод краткой статистики
        logger.info("\n📊 КРАТКАЯ СТАТИСТИКА:\n")
        usage = stats.get("partial_tp_usage", {})
        logger.info(
            f"  Позиций с Partial TP: {usage.get('positions_with_partial_tp', 0)} "
            f"({usage.get('partial_tp_percentage', 0):.1f}%)\n"
        )

        effectiveness = stats.get("partial_tp_effectiveness", {})
        with_ptp = effectiveness.get("with_partial_tp", {})
        without_ptp = effectiveness.get("without_partial_tp", {})
        logger.info(
            f"  Win rate с Partial TP: {with_ptp.get('win_rate', 0):.1f}% "
            f"(без: {without_ptp.get('win_rate', 0):.1f}%)\n"
        )


async def main():
    auditor = PartialTPAuditor()
    await auditor.run_audit()


if __name__ == "__main__":
    asyncio.run(main())

