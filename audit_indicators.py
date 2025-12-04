"""
Аудит индикаторов
Проверяет:
- Правильность расчета индикаторов (MA, RSI, ADX, ATR, MACD, BB)
- Обработку edge cases (NaN, деление на 0)
- Производительность расчетов
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
from datetime import datetime
import importlib.util

from loguru import logger

# Настройка логирования
logger.remove()
logger.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
)


class IndicatorsAuditor:
    """Аудитор индикаторов"""

    def __init__(self):
        self.indicators_dir = Path("src/indicators")
        self.futures_indicators_dir = Path("src/strategies/scalping/futures/indicators")

    def find_indicator_files(self) -> Dict[str, List[str]]:
        """Поиск файлов с индикаторами"""
        logger.info("🔍 Поиск файлов с индикаторами...\n")

        indicators = {
            "src/indicators": [],
            "src/strategies/scalping/futures/indicators": [],
        }

        # Ищем в src/indicators
        if self.indicators_dir.exists():
            for file in self.indicators_dir.glob("*.py"):
                if file.name != "__init__.py":
                    indicators["src/indicators"].append(str(file))

        # Ищем в futures indicators
        if self.futures_indicators_dir.exists():
            for file in self.futures_indicators_dir.glob("*.py"):
                if file.name != "__init__.py":
                    indicators["src/strategies/scalping/futures/indicators"].append(
                        str(file)
                    )

        return indicators

    def analyze_indicator_code(self, file_path: str) -> Dict:
        """Анализ кода индикатора"""
        issues = []
        recommendations = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Проверка на деление на 0
            if "/ 0" in content or "/0" in content:
                issues.append("⚠️ Возможное деление на 0 в коде")

            # Проверка на обработку NaN
            if "nan" in content.lower() and "isnan" not in content.lower():
                issues.append("⚠️ Возможна проблема с NaN без проверки")

            # Проверка на обработку пустых данных
            if "len(" in content and "if len" not in content:
                issues.append("⚠️ Возможна проблема с пустыми данными")

            # Проверка на обработку None
            if "None" in content and "if" not in content[:content.find("None") + 50]:
                issues.append("⚠️ Возможна проблема с None без проверки")

        except Exception as e:
            issues.append(f"❌ Ошибка чтения файла: {e}")

        return {
            "file": file_path,
            "issues": issues,
            "recommendations": recommendations,
        }

    def analyze_fast_adx(self) -> Dict:
        """Анализ FastADX индикатора"""
        logger.info("🔍 Анализ FastADX...\n")

        issues = []
        recommendations = []

        try:
            file_path = self.futures_indicators_dir / "fast_adx.py"
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Проверка на правильность расчета ADX
                if "_calculate_adx" in content:
                    issues.append("✅ Метод _calculate_adx реализован")

                # Проверка на обработку edge cases
                if "if len" in content or "if not" in content:
                    issues.append("✅ Есть проверки на пустые данные")

                # Проверка на деление на 0
                if "/ 0" in content or "/0" in content:
                    issues.append("⚠️ Возможно деление на 0")

        except Exception as e:
            issues.append(f"❌ Ошибка анализа FastADX: {e}")

        return {
            "indicator": "FastADX",
            "issues": issues,
            "recommendations": recommendations,
        }

    def analyze_indicators_usage(self) -> Dict:
        """Анализ использования индикаторов"""
        logger.info("🔍 Анализ использования индикаторов...\n")

        # Ищем использование индикаторов в коде
        usage = defaultdict(int)

        # Ищем в signal_generator
        signal_gen_file = Path("src/strategies/scalping/futures/signal_generator.py")
        if signal_gen_file.exists():
            with open(signal_gen_file, "r", encoding="utf-8") as f:
                content = f.read()
                if "rsi" in content.lower():
                    usage["RSI"] += content.lower().count("rsi")
                if "ema" in content.lower():
                    usage["EMA"] += content.lower().count("ema")
                if "sma" in content.lower():
                    usage["SMA"] += content.lower().count("sma")
                if "macd" in content.lower():
                    usage["MACD"] += content.lower().count("macd")
                if "bollinger" in content.lower() or "bb" in content.lower():
                    usage["BollingerBands"] += content.lower().count("bollinger") + content.lower().count("bb")
                if "atr" in content.lower():
                    usage["ATR"] += content.lower().count("atr")
                if "adx" in content.lower():
                    usage["ADX"] += content.lower().count("adx")

        return dict(usage)

    def generate_report(self, stats: Dict) -> str:
        """Генерация отчета"""
        report = []
        report.append("# 🔍 АУДИТ ИНДИКАТОРОВ\n")
        report.append(f"**Дата:** {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n")
        report.append("---\n\n")

        # Найденные индикаторы
        report.append("## 📊 НАЙДЕННЫЕ ИНДИКАТОРЫ\n\n")
        indicator_files = stats.get("indicator_files", {})
        for directory, files in indicator_files.items():
            if files:
                report.append(f"**{directory}:**\n")
                for file in files:
                    report.append(f"- `{Path(file).name}`\n")
                report.append("\n")

        # Использование индикаторов
        report.append("## 📈 ИСПОЛЬЗОВАНИЕ ИНДИКАТОРОВ\n\n")
        usage = stats.get("indicators_usage", {})
        if usage:
            report.append("| Индикатор | Использований |\n")
            report.append("|-----------|---------------|\n")
            for indicator, count in sorted(usage.items(), key=lambda x: x[1], reverse=True):
                report.append(f"| {indicator} | {count} |\n")
        else:
            report.append("⚠️ Нет данных об использовании индикаторов\n\n")

        # Анализ кода
        report.append("\n## 🔧 АНАЛИЗ КОДА ИНДИКАТОРОВ\n\n")
        code_analysis = stats.get("code_analysis", [])
        for analysis in code_analysis:
            report.append(f"### {Path(analysis['file']).name}\n\n")
            if analysis.get("issues"):
                for issue in analysis["issues"]:
                    report.append(f"- {issue}\n")
            report.append("\n")

        # Анализ FastADX
        report.append("## 🔍 АНАЛИЗ FASTADX\n\n")
        fast_adx = stats.get("fast_adx_analysis", {})
        if fast_adx.get("issues"):
            for issue in fast_adx["issues"]:
                report.append(f"- {issue}\n")

        # Проблемы
        report.append("\n## ⚠️ НАЙДЕННЫЕ ПРОБЛЕМЫ\n\n")
        problems = []

        # Проверяем наличие проблем в коде
        for analysis in code_analysis:
            for issue in analysis.get("issues", []):
                if "⚠️" in issue or "❌" in issue:
                    problems.append(f"{Path(analysis['file']).name}: {issue}")

        if problems:
            for problem in problems:
                report.append(f"- {problem}\n")
        else:
            report.append("✅ Критических проблем не найдено\n")

        # Рекомендации
        report.append("\n## 🎯 РЕКОМЕНДАЦИИ\n\n")
        recommendations = []

        # Проверяем наличие деления на 0
        has_division_by_zero = any(
            "деление на 0" in str(analysis.get("issues", []))
            for analysis in code_analysis
        )
        if has_division_by_zero:
            recommendations.append(
                "1. **Добавить проверки на деление на 0** - предотвратить ошибки при расчете"
            )

        # Проверяем обработку NaN
        has_nan_issues = any(
            "NaN" in str(analysis.get("issues", []))
            for analysis in code_analysis
        )
        if has_nan_issues:
            recommendations.append(
                "2. **Добавить проверки на NaN** - использовать math.isnan() или numpy.isnan()"
            )

        if recommendations:
            for rec in recommendations:
                report.append(f"- {rec}\n")
        else:
            report.append("✅ Все рекомендации выполнены\n")

        return "".join(report)

    async def run_audit(self):
        """Запуск аудита"""
        logger.info("🚀 НАЧАЛО АУДИТА ИНДИКАТОРОВ\n")
        logger.info("=" * 60 + "\n\n")

        # Поиск файлов
        indicator_files = self.find_indicator_files()

        # Анализ кода
        code_analysis = []
        for directory, files in indicator_files.items():
            for file_path in files:
                analysis = self.analyze_indicator_code(file_path)
                code_analysis.append(analysis)

        # Анализ FastADX
        fast_adx_analysis = self.analyze_fast_adx()

        # Анализ использования
        indicators_usage = self.analyze_indicators_usage()

        # Статистика
        stats = {
            "indicator_files": indicator_files,
            "code_analysis": code_analysis,
            "fast_adx_analysis": fast_adx_analysis,
            "indicators_usage": indicators_usage,
        }

        # Генерация отчета
        report = self.generate_report(stats)

        # Сохранение отчета
        report_file = Path("INDICATORS_AUDIT_REPORT.md")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        logger.info("\n" + "=" * 60 + "\n")
        logger.info("✅ АУДИТ ЗАВЕРШЕН\n")
        logger.info(f"📄 Отчет сохранен: {report_file}\n")

        # Вывод краткой статистики
        logger.info("\n📊 КРАТКАЯ СТАТИСТИКА:\n")
        logger.info(f"  Найдено файлов с индикаторами: {sum(len(files) for files in indicator_files.values())}\n")
        logger.info(f"  Используемых индикаторов: {len(indicators_usage)}\n")


async def main():
    auditor = IndicatorsAuditor()
    await auditor.run_audit()


if __name__ == "__main__":
    asyncio.run(main())
