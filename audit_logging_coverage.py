"""
Аудит покрытия логированием всех функций бота
Проверяет:
- Логирование всех ключевых операций
- Логирование сигналов и фильтров
- Логирование открытия/закрытия позиций
- Логирование exit mechanisms
- Логирование рисков и ошибок
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

from loguru import logger

# Настройка логирования
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
)


class LoggingCoverageAuditor:
    """Аудитор покрытия логированием"""

    def __init__(self):
        self.futures_dir = Path("src/strategies/scalping/futures")
        self.key_operations = {
            "signal_generation": ["generate", "signal", "rsi", "macd", "ma", "bb"],
            "filtering": ["filter", "adx", "mtf", "correlation", "pivot"],
            "position_opening": ["open_position", "entry", "place_order"],
            "position_closing": ["close_position", "exit", "tp", "sl", "trailing"],
            "risk_management": ["risk", "margin", "size", "limit"],
            "order_execution": ["execute", "order", "market", "limit", "fill"],
            "exit_mechanisms": [
                "tp",
                "sl",
                "partial",
                "harvest",
                "timeout",
                "emergency",
            ],
            "regime_detection": ["regime", "trending", "ranging", "choppy"],
            "pnl_calculation": ["pnl", "profit", "loss", "margin"],
            "slippage": ["slippage", "spread", "fill"],
        }

    def find_key_functions(self) -> Dict[str, List[str]]:
        """Поиск ключевых функций в коде"""
        logger.info("🔍 Поиск ключевых функций...\n")

        functions = defaultdict(list)

        # Ищем функции в основных файлах
        for py_file in self.futures_dir.rglob("*.py"):
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Ищем определения функций
                func_pattern = r"async def (\w+)|def (\w+)"
                matches = re.findall(func_pattern, content)

                for match in matches:
                    func_name = match[0] or match[1]
                    # Проверяем, относится ли функция к ключевым операциям
                    for op_type, keywords in self.key_operations.items():
                        if any(keyword in func_name.lower() for keyword in keywords):
                            functions[op_type].append(f"{py_file.name}:{func_name}")

            except Exception as e:
                logger.debug(f"⚠️ Ошибка чтения {py_file}: {e}")

        return dict(functions)

    def check_logging_in_functions(self) -> Dict[str, Dict[str, bool]]:
        """Проверка наличия логирования в функциях"""
        logger.info("🔍 Проверка логирования в функциях...\n")

        coverage = defaultdict(lambda: defaultdict(bool))

        # Проверяем ключевые файлы
        key_files = {
            "signal_generation": [
                "signal_generator.py",
                "coordinators/signal_coordinator.py",
            ],
            "filtering": ["signals/filter_manager.py"],
            "position_opening": ["positions/entry_manager.py"],
            "position_closing": [
                "position_manager.py",
                "positions/exit_analyzer.py",
            ],
            "risk_management": ["risk_manager.py"],
            "order_execution": ["order_executor.py"],
            "exit_mechanisms": [
                "position_manager.py",
                "positions/exit_analyzer.py",
                "indicators/trailing_stop_loss.py",
            ],
            "regime_detection": [
                "adaptivity/regime_manager.py",
                "modules/adaptive_regime_manager.py",
            ],
            "pnl_calculation": [
                "calculations/pnl_calculator.py",
                "position_manager.py",
            ],
            "slippage": ["modules/slippage_guard.py", "order_executor.py"],
        }

        for op_type, files in key_files.items():
            for file_rel in files:
                file_path = self.futures_dir / file_rel
                if file_path.exists():
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                        # Проверяем наличие логирования
                        has_info = "logger.info" in content
                        has_warning = "logger.warning" in content
                        has_error = "logger.error" in content
                        has_debug = "logger.debug" in content

                        coverage[op_type][file_rel] = (
                            has_info or has_warning or has_error or has_debug
                        )

                    except Exception as e:
                        logger.debug(f"⚠️ Ошибка чтения {file_path}: {e}")

        return dict(coverage)

    def check_specific_logging(self) -> Dict[str, bool]:
        """Проверка конкретных типов логирования"""
        logger.info("🔍 Проверка конкретных типов логирования...\n")

        checks = {
            "signal_types": False,
            "filters_passed": False,
            "regime_logging": False,
            "slippage_logging": False,
            "partial_tp_logging": False,
            "exit_reasons": False,
            "daily_pnl": False,
            "max_daily_loss": False,
        }

        # Проверяем signal_coordinator для типов сигналов
        signal_coord_file = self.futures_dir / "coordinators" / "signal_coordinator.py"
        if signal_coord_file.exists():
            with open(signal_coord_file, "r", encoding="utf-8") as f:
                content = f.read()
                checks["signal_types"] = (
                    "signal_type" in content and "logger.info" in content
                )

        # Проверяем filter_manager для filters_passed
        filter_mgr_file = self.futures_dir / "signals" / "filter_manager.py"
        if filter_mgr_file.exists():
            with open(filter_mgr_file, "r", encoding="utf-8") as f:
                content = f.read()
                checks["filters_passed"] = (
                    "filters_passed" in content and "logger" in content
                )

        # Проверяем regime логирование
        regime_files = [
            self.futures_dir / "adaptivity" / "regime_manager.py",
            self.futures_dir / "modules" / "adaptive_regime_manager.py",
        ]
        for file_path in regime_files:
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if "regime" in content.lower() and "logger" in content:
                        checks["regime_logging"] = True
                        break

        # Проверяем slippage логирование
        slippage_file = Path("src/strategies/modules/slippage_guard.py")
        order_exec_file = self.futures_dir / "order_executor.py"
        for file_path in [slippage_file, order_exec_file]:
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if "slippage" in content.lower() and "logger" in content:
                        checks["slippage_logging"] = True
                        break

        # Проверяем partial_tp логирование
        position_mgr_file = self.futures_dir / "position_manager.py"
        if position_mgr_file.exists():
            with open(position_mgr_file, "r", encoding="utf-8") as f:
                content = f.read()
                checks["partial_tp_logging"] = (
                    "partial_tp" in content.lower() and "logger" in content
                )

        # Проверяем exit_reasons
        exit_analyzer_file = self.futures_dir / "positions" / "exit_analyzer.py"
        if exit_analyzer_file.exists():
            with open(exit_analyzer_file, "r", encoding="utf-8") as f:
                content = f.read()
                checks["exit_reasons"] = (
                    "reason" in content.lower() and "logger" in content
                )

        # Проверяем daily_pnl и max_daily_loss
        risk_mgr_file = self.futures_dir / "risk_manager.py"
        if risk_mgr_file.exists():
            with open(risk_mgr_file, "r", encoding="utf-8") as f:
                content = f.read()
                checks["daily_pnl"] = "daily_pnl" in content and "logger" in content
                checks["max_daily_loss"] = (
                    "max_daily_loss" in content and "logger" in content
                )

        return checks

    def generate_report(self, stats: Dict) -> str:
        """Генерация отчета"""
        report = []
        report.append("# 🔍 АУДИТ ПОКРЫТИЯ ЛОГИРОВАНИЕМ\n")
        report.append("**Дата:** 04.12.2025\n")
        report.append("---\n\n")

        # Проверка конкретных типов логирования
        report.append("## ✅ ПРОВЕРКА КОНКРЕТНЫХ ТИПОВ ЛОГИРОВАНИЯ\n\n")
        specific = stats.get("specific_logging", {})
        for check_name, has_logging in specific.items():
            status = "✅" if has_logging else "❌"
            report.append(
                f"{status} **{check_name}**: {'Есть' if has_logging else 'НЕТ'}\n"
            )

        # Покрытие по типам операций
        report.append("\n## 📊 ПОКРЫТИЕ ПО ТИПАМ ОПЕРАЦИЙ\n\n")
        coverage = stats.get("function_coverage", {})
        for op_type, files in coverage.items():
            report.append(f"### {op_type.replace('_', ' ').title()}\n\n")
            total = len(files)
            covered = sum(1 for has_logging in files.values() if has_logging)
            report.append(
                f"**Покрытие:** {covered}/{total} ({covered/total*100:.0f}%)\n\n"
            )
            for file_rel, has_logging in files.items():
                status = "✅" if has_logging else "❌"
                report.append(f"{status} `{file_rel}`\n")

        # Проблемы
        report.append("\n## ⚠️ НАЙДЕННЫЕ ПРОБЛЕМЫ\n\n")
        problems = []
        for check_name, has_logging in specific.items():
            if not has_logging:
                problems.append(f"1. **{check_name}** - нет логирования")

        if problems:
            for problem in problems:
                report.append(f"- {problem}\n")
        else:
            report.append("✅ Критических проблем не найдено\n")

        # Рекомендации
        report.append("\n## 🎯 РЕКОМЕНДАЦИИ\n\n")
        recommendations = []
        for check_name, has_logging in specific.items():
            if not has_logging:
                recommendations.append(
                    f"1. **Добавить логирование {check_name}** - для полного покрытия"
                )

        if recommendations:
            for rec in recommendations:
                report.append(f"- {rec}\n")
        else:
            report.append("✅ Все рекомендации выполнены\n")

        return "".join(report)

    async def run_audit(self):
        """Запуск аудита"""
        logger.info("🚀 НАЧАЛО АУДИТА ПОКРЫТИЯ ЛОГИРОВАНИЕМ\n")
        logger.info("=" * 60 + "\n\n")

        # Поиск функций
        functions = self.find_key_functions()

        # Проверка логирования
        function_coverage = self.check_logging_in_functions()

        # Проверка конкретных типов
        specific_logging = self.check_specific_logging()

        # Статистика
        stats = {
            "functions": functions,
            "function_coverage": function_coverage,
            "specific_logging": specific_logging,
        }

        # Генерация отчета
        report = self.generate_report(stats)

        # Сохранение отчета
        report_file = Path("LOGGING_COVERAGE_AUDIT_REPORT.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        logger.info("\n" + "=" * 60 + "\n")
        logger.info("✅ АУДИТ ЗАВЕРШЕН\n")
        logger.info(f"📄 Отчет сохранен: {report_file}\n")

        # Вывод краткой статистики
        logger.info("\n📊 КРАТКАЯ СТАТИСТИКА:\n")
        total_checks = len(specific_logging)
        passed_checks = sum(1 for v in specific_logging.values() if v)
        logger.info(
            f"  Проверок логирования: {passed_checks}/{total_checks} ({passed_checks/total_checks*100:.0f}%)\n"
        )


async def main():
    auditor = LoggingCoverageAuditor()
    await auditor.run_audit()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
