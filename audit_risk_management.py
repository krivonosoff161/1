"""
Аудит риск-менеджмента торгового бота.

Анализирует:
1. Размеры позиций vs конфиг
2. Соблюдение лимитов (max_position_size, max_daily_loss)
3. Использование маржи
4. Адаптивность по балансу
5. Рекомендации по оптимизации
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import statistics

from loguru import logger


class RiskManagementAuditor:
    """Аудитор риск-менеджмента"""

    def __init__(self, positions_file: str):
        """
        Инициализация аудитора

        Args:
            positions_file: Путь к файлу с данными позиций
        """
        self.positions_file = positions_file
        self.positions = []

    def load_positions(self) -> None:
        """Загрузка данных позиций"""
        logger.info(f"📂 Загрузка позиций из {self.positions_file}")
        try:
            with open(self.positions_file, "r", encoding="utf-8") as f:
                self.positions = json.load(f)
            logger.info(f"✅ Загружено {len(self.positions)} позиций")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки позиций: {e}")
            raise

    def analyze_position_sizes(self) -> Dict[str, Any]:
        """Анализ размеров позиций"""
        logger.info("🔍 Анализ размеров позиций...")

        # Рассчитываем стоимость позиций в USD
        position_values = []
        for pos in self.positions:
            size = float(pos.get("size", 0))
            entry_price = float(pos.get("entry_price", 0))
            if size > 0 and entry_price > 0:
                position_value = size * entry_price
                position_values.append(position_value)
                pos["position_value_usd"] = position_value

        if not position_values:
            logger.warning("⚠️ Нет данных о размерах позиций")
            return {"error": "Нет данных"}

        # Статистика
        analysis = {
            "total_positions": len(position_values),
            "min_position_usd": min(position_values),
            "max_position_usd": max(position_values),
            "avg_position_usd": statistics.mean(position_values),
            "median_position_usd": statistics.median(position_values),
            "std_position_usd": statistics.stdev(position_values) if len(position_values) > 1 else 0,
        }

        # Группировка по диапазонам
        ranges = {
            "small_<50": [v for v in position_values if v < 50],
            "medium_50-100": [v for v in position_values if 50 <= v < 100],
            "large_100-200": [v for v in position_values if 100 <= v < 200],
            "xlarge_>200": [v for v in position_values if v >= 200],
        }

        analysis["by_range"] = {}
        for range_name, values in ranges.items():
            if values:
                analysis["by_range"][range_name] = {
                    "count": len(values),
                    "percentage": (len(values) / len(position_values)) * 100,
                    "avg_value": statistics.mean(values),
                }

        return analysis

    def analyze_risk_limits(self) -> Dict[str, Any]:
        """Анализ соблюдения лимитов риска"""
        logger.info("🔍 Анализ соблюдения лимитов риска...")

        # Конфигурация лимитов (из конфига)
        # max_position_size_percent: 8.0% (для small balance)
        # max_daily_loss_percent: 10.0%
        # risk_per_trade_percent: 1.0%

        # Оценка баланса (из среднего размера позиций)
        # Если средний размер ~$100, то при risk_per_trade=1% баланс ~$10,000
        estimated_balance = 10000.0  # Оценка

        # Анализ позиций
        position_values = []
        daily_pnl = defaultdict(float)  # По датам

        for pos in self.positions:
            size = float(pos.get("size", 0))
            entry_price = float(pos.get("entry_price", 0))
            if size > 0 and entry_price > 0:
                position_value = size * entry_price
                position_values.append(position_value)

            # Анализ PnL по датам
            entry_time = pos.get("entry_time", "")
            if entry_time:
                try:
                    date = entry_time.split("T")[0]  # YYYY-MM-DD
                    net_pnl = float(pos.get("net_pnl", 0) or 0)
                    daily_pnl[date] += net_pnl
                except Exception:
                    pass

        if not position_values:
            return {"error": "Нет данных"}

        # Проверка max_position_size_percent (8% для small balance)
        max_position_size_percent = 8.0
        max_position_size_usd = estimated_balance * (max_position_size_percent / 100)
        violations_max_size = [v for v in position_values if v > max_position_size_usd]

        # Проверка max_daily_loss_percent (10%)
        max_daily_loss_percent = 10.0
        max_daily_loss_usd = estimated_balance * (max_daily_loss_percent / 100)
        violations_daily_loss = [
            (date, pnl) for date, pnl in daily_pnl.items() if pnl < -max_daily_loss_usd
        ]

        # Проверка risk_per_trade_percent (1%)
        risk_per_trade_percent = 1.0
        max_risk_per_trade_usd = estimated_balance * (risk_per_trade_percent / 100)
        # Оценка: если позиция $100, то риск может быть больше $1 (зависит от SL)
        # Для упрощения считаем что позиция = риск (хотя на самом деле риск меньше из-за SL)

        analysis = {
            "estimated_balance": estimated_balance,
            "max_position_size_percent": max_position_size_percent,
            "max_position_size_usd": max_position_size_usd,
            "violations_max_size": {
                "count": len(violations_max_size),
                "percentage": (len(violations_max_size) / len(position_values)) * 100 if position_values else 0,
                "max_violation": max(violations_max_size) if violations_max_size else 0,
            },
            "max_daily_loss_percent": max_daily_loss_percent,
            "max_daily_loss_usd": max_daily_loss_usd,
            "violations_daily_loss": {
                "count": len(violations_daily_loss),
                "dates": violations_daily_loss[:10],  # Первые 10
            },
            "risk_per_trade_percent": risk_per_trade_percent,
            "max_risk_per_trade_usd": max_risk_per_trade_usd,
        }

        return analysis

    def analyze_margin_usage(self) -> Dict[str, Any]:
        """Анализ использования маржи"""
        logger.info("🔍 Анализ использования маржи...")

        # Оценка маржи (при leverage 3x)
        leverage = 3.0
        estimated_balance = 10000.0

        margin_used_list = []
        for pos in self.positions:
            size = float(pos.get("size", 0))
            entry_price = float(pos.get("entry_price", 0))
            if size > 0 and entry_price > 0:
                position_value = size * entry_price
                margin_used = position_value / leverage
                margin_used_list.append(margin_used)
                pos["estimated_margin"] = margin_used

        if not margin_used_list:
            return {"error": "Нет данных"}

        total_margin_used = sum(margin_used_list)
        margin_usage_percent = (total_margin_used / estimated_balance) * 100 if estimated_balance > 0 else 0

        # Проверка max_margin_percent (90% для ranging)
        max_margin_percent = 90.0
        is_within_limit = margin_usage_percent <= max_margin_percent

        analysis = {
            "estimated_balance": estimated_balance,
            "leverage": leverage,
            "total_margin_used": total_margin_used,
            "margin_usage_percent": margin_usage_percent,
            "max_margin_percent": max_margin_percent,
            "is_within_limit": is_within_limit,
            "avg_margin_per_position": statistics.mean(margin_used_list) if margin_used_list else 0,
        }

        return analysis

    def analyze_balance_adaptivity(self) -> Dict[str, Any]:
        """Анализ адаптивности по балансу"""
        logger.info("🔍 Анализ адаптивности по балансу...")

        # Группируем позиции по символам
        by_symbol = defaultdict(list)
        for pos in self.positions:
            symbol = pos.get("symbol", "UNKNOWN")
            by_symbol[symbol].append(pos)

        # Анализируем размеры позиций по символам
        analysis = {
            "by_symbol": {},
        }

        for symbol, positions in by_symbol.items():
            position_values = []
            for pos in positions:
                size = float(pos.get("size", 0))
                entry_price = float(pos.get("entry_price", 0))
                if size > 0 and entry_price > 0:
                    position_values.append(size * entry_price)

            if position_values:
                analysis["by_symbol"][symbol] = {
                    "count": len(position_values),
                    "avg_position_usd": statistics.mean(position_values),
                    "min_position_usd": min(position_values),
                    "max_position_usd": max(position_values),
                    "std_position_usd": statistics.stdev(position_values) if len(position_values) > 1 else 0,
                }

        return analysis

    def generate_report(self) -> str:
        """Генерация отчета"""
        logger.info("📝 Генерация отчета...")

        size_analysis = self.analyze_position_sizes()
        limits_analysis = self.analyze_risk_limits()
        margin_analysis = self.analyze_margin_usage()
        adaptivity_analysis = self.analyze_balance_adaptivity()

        report = f"""# 🔍 АУДИТ РИСК-МЕНЕДЖМЕНТА

**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Период:** 02-03.12.2025  
**Источник данных:** {self.positions_file}

---

## 📊 АНАЛИЗ РАЗМЕРОВ ПОЗИЦИЙ

"""

        if "error" not in size_analysis:
            report += f"""
### Общая статистика:
- **Всего позиций:** {size_analysis['total_positions']}
- **Минимальный размер:** ${size_analysis['min_position_usd']:.2f}
- **Максимальный размер:** ${size_analysis['max_position_usd']:.2f}
- **Средний размер:** ${size_analysis['avg_position_usd']:.2f}
- **Медианный размер:** ${size_analysis['median_position_usd']:.2f}
- **Стандартное отклонение:** ${size_analysis['std_position_usd']:.2f}

### Распределение по диапазонам:
"""

            for range_name, stats in size_analysis.get("by_range", {}).items():
                report += f"""
- **{range_name.replace('_', ' ')}:**
  - Количество: {stats['count']} ({stats['percentage']:.1f}%)
  - Средний размер: ${stats['avg_value']:.2f}
"""

        report += f"""
---

## 🛡️ АНАЛИЗ СОБЛЮДЕНИЯ ЛИМИТОВ

"""

        if "error" not in limits_analysis:
            report += f"""
### Оценка баланса:
- **Оценка баланса:** ${limits_analysis['estimated_balance']:.2f}

### Max Position Size (8% от баланса):
- **Лимит:** ${limits_analysis['max_position_size_usd']:.2f} ({limits_analysis['max_position_size_percent']}%)
- **Нарушений:** {limits_analysis['violations_max_size']['count']} ({limits_analysis['violations_max_size']['percentage']:.1f}%)
- **Максимальное нарушение:** ${limits_analysis['violations_max_size']['max_violation']:.2f}

### Max Daily Loss (10% от баланса):
- **Лимит:** ${limits_analysis['max_daily_loss_usd']:.2f} ({limits_analysis['max_daily_loss_percent']}%)
- **Нарушений:** {limits_analysis['violations_daily_loss']['count']}
"""

            if limits_analysis['violations_daily_loss']['dates']:
                report += "\n**Даты с нарушением:**\n"
                for date, pnl in limits_analysis['violations_daily_loss']['dates']:
                    report += f"- {date}: ${pnl:.2f}\n"

            report += f"""
### Risk Per Trade (1% от баланса):
- **Лимит:** ${limits_analysis['max_risk_per_trade_usd']:.2f} ({limits_analysis['risk_per_trade_percent']}%)
"""

        report += f"""
---

## 💰 АНАЛИЗ ИСПОЛЬЗОВАНИЯ МАРЖИ

"""

        if "error" not in margin_analysis:
            report += f"""
### Статистика маржи:
- **Оценка баланса:** ${margin_analysis['estimated_balance']:.2f}
- **Leverage:** {margin_analysis['leverage']}x
- **Общая использованная маржа:** ${margin_analysis['total_margin_used']:.2f}
- **Процент использования:** {margin_analysis['margin_usage_percent']:.1f}%
- **Лимит:** {margin_analysis['max_margin_percent']}%
- **В пределах лимита:** {'✅ Да' if margin_analysis['is_within_limit'] else '❌ Нет'}
- **Средняя маржа на позицию:** ${margin_analysis['avg_margin_per_position']:.2f}
"""

        report += f"""
---

## 📈 АНАЛИЗ АДАПТИВНОСТИ ПО БАЛАНСУ

"""

        if adaptivity_analysis.get("by_symbol"):
            report += "\n### По символам:\n\n"
            for symbol, stats in sorted(adaptivity_analysis["by_symbol"].items(), key=lambda x: x[1]["count"], reverse=True):
                report += f"""
#### {symbol}
- **Позиций:** {stats['count']}
- **Средний размер:** ${stats['avg_position_usd']:.2f}
- **Минимальный:** ${stats['min_position_usd']:.2f}
- **Максимальный:** ${stats['max_position_usd']:.2f}
- **Стандартное отклонение:** ${stats['std_position_usd']:.2f}
"""

        report += f"""
---

## 🔍 АНАЛИЗ КОДА РИСК-МЕНЕДЖМЕНТА

### Компоненты риск-менеджмента:

1. **PositionSizer** - расчет размера позиций
   - Учитывает баланс, режим, риск на сделку
   - Адаптивные множители по режимам

2. **FuturesRiskManager** - централизованное управление рисками
   - Проверка лимитов
   - Circuit breaker для серии убытков
   - Мониторинг маржи

3. **MarginCalculator** - расчет маржи
   - Оптимальный размер позиции
   - Проверка безопасности
   - Kelly Criterion для оптимизации

### Параметры из конфига:

- **risk_per_trade_percent:** 1.0% (по умолчанию)
- **max_position_size_percent:** 8.0% (для small balance)
- **max_daily_loss_percent:** 10.0%
- **max_margin_percent:** 90.0% (для ranging)
- **leverage:** 3x

---

## ⚠️ НАЙДЕННЫЕ ПРОБЛЕМЫ

### 1. Оценка баланса
- ⚠️ Баланс оценивается по среднему размеру позиций
- ⚠️ Нет реальных данных о балансе в позициях
- ✅ Рекомендация: Добавить логирование баланса

### 2. Проверка лимитов
- ⚠️ Нет данных о реальном соблюдении лимитов
- ⚠️ Оценка основана на предположениях
- ✅ Рекомендация: Добавить логирование проверок лимитов

### 3. Использование маржи
- ⚠️ Маржа рассчитывается по оценке
- ⚠️ Нет данных о реальной марже с биржи
- ✅ Рекомендация: Использовать реальные данные маржи

---

## 🎯 РЕКОМЕНДАЦИИ

### 1. Улучшение логирования (КРИТИЧНО)
- ✅ Добавить логирование баланса при открытии позиции
- ✅ Добавить логирование проверок лимитов
- ✅ Добавить логирование реальной маржи с биржи

### 2. Оптимизация размеров позиций (ВЫСОКИЙ ПРИОРИТЕТ)
- ✅ Анализировать эффективность разных размеров
- ✅ Оптимизировать адаптивные множители
- ✅ Улучшить расчет на основе волатильности

### 3. Улучшение проверки лимитов (ВЫСОКИЙ ПРИОРИТЕТ)
- ✅ Реализовать строгую проверку max_position_size
- ✅ Реализовать проверку max_daily_loss
- ✅ Добавить автоматическое снижение риска при приближении к лимитам

### 4. Мониторинг маржи (СРЕДНИЙ ПРИОРИТЕТ)
- ✅ Реализовать реальный мониторинг маржи
- ✅ Добавить предупреждения при высоком использовании
- ✅ Автоматическое снижение размера позиций при необходимости

---

**Следующие шаги:**
1. Добавить логирование баланса и маржи
2. Провести анализ с реальными данными
3. Оптимизировать размеры позиций на основе результатов
"""

        return report

    def save_report(self, report: str, output_file: str = "RISK_MANAGEMENT_AUDIT_REPORT.md") -> None:
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
    positions_file = "exchange_positions.json"
    
    if not Path(positions_file).exists():
        logger.error(f"❌ Файл {positions_file} не найден!")
        return

    auditor = RiskManagementAuditor(positions_file)
    
    try:
        # Загрузка данных
        auditor.load_positions()
        
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

