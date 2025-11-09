#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Универсальный анализатор логов торгового бота
Гибридный вариант: меню + параметры командной строки + конфиг
"""

import argparse
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib import style

    MATPLOTLIB_AVAILABLE = True
    style.use("seaborn-v0_8-darkgrid")
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print(
        "⚠️ Matplotlib не установлен. Графики будут недоступны. Установите: pip install matplotlib"
    )

try:
    from jinja2 import Template

    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False
    print(
        "⚠️ Jinja2 не установлен. HTML отчеты будут упрощенными. Установите: pip install jinja2"
    )


@dataclass
class SessionStats:
    """Статистика сессии"""

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[timedelta] = None

    # Финансы
    start_balance: float = 0.0
    end_balance: float = 0.0
    profit: float = 0.0
    profit_percent: float = 0.0
    commissions: float = 0.0

    # Ордера
    orders_placed: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    orders_failed: int = 0
    order_effectiveness: float = 0.0

    # Позиции
    positions_opened: int = 0
    positions_closed: int = 0
    positions_profitable: int = 0
    positions_loss: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0

    # Сигналы
    signals_generated: int = 0
    signals_executed: int = 0
    signals_blocked: int = 0

    # Ошибки
    errors_count: int = 0
    warnings_count: int = 0
    critical_errors: int = 0

    # Производительность
    avg_order_time: float = 0.0
    avg_position_duration: float = 0.0


class LogAnalyzer:
    """Анализатор логов"""

    def __init__(self, logs_dir: str = "logs"):
        self.logs_dir = Path(logs_dir)
        self.log_files: List[Path] = []
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """Загрузка конфигурации"""
        config_path = self.logs_dir / "log_analyzer_config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass

        # Конфиг по умолчанию
        return {
            "filters": {
                "levels": ["INFO", "WARNING", "ERROR", "CRITICAL"],
                "keywords": [],
                "exclude": [],
            },
            "reports": {"format": "html", "charts": True, "save_path": "logs/reports"},
            "analysis": {
                "show_duplicates": True,
                "show_errors": True,
                "show_performance": True,
                "compare_sessions": True,
            },
        }

    def find_log_files(
        self, date: Optional[str] = None, time_range: Optional[Tuple[str, str]] = None
    ) -> List[Path]:
        """Поиск файлов логов"""
        log_files = []

        # Поиск в папке futures
        futures_dir = self.logs_dir / "futures"
        if futures_dir.exists():
            # Ищем .log файлы в корне (исторический формат)
            for log_file in futures_dir.glob("*.log"):
                if log_file.is_file() and not log_file.name.endswith(".zip"):
                    log_files.append(log_file)

            # Ищем .log файлы в подпапках (новый распакованный формат)
            for subdir in futures_dir.iterdir():
                if subdir.is_dir():
                    for nested_log in subdir.glob("*.log"):
                        if not nested_log.is_file():
                            continue
                        log_files.append(nested_log)

            # Ищем .zip архивы
            for zip_file in futures_dir.glob("*.zip"):
                log_files.append(zip_file)

        # Фильтрация по дате
        if date:
            filtered = []
            for log_file in log_files:
                if date in log_file.name:
                    filtered.append(log_file)
            log_files = filtered

        # Сортировка по времени
        log_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        self.log_files = log_files
        return log_files

    def read_log_file(self, log_file: Path) -> List[str]:
        """Чтение лог файла (поддерживает zip)"""
        lines = []

        try:
            if log_file.suffix == ".zip":
                # Читаем из архива
                with zipfile.ZipFile(log_file, "r") as zip_ref:
                    # Получаем имя файла в архиве
                    file_list = zip_ref.namelist()
                    if file_list:
                        with zip_ref.open(file_list[0]) as f:
                            lines = (
                                f.read().decode("utf-8", errors="ignore").splitlines()
                            )
            else:
                # Читаем обычный файл
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
        except Exception as e:
            print(f"⚠️ Ошибка чтения {log_file}: {e}")

        return lines

    def parse_log_line(self, line: str) -> Optional[Dict]:
        """Парсинг строки лога"""
        # Формат: YYYY-MM-DD HH:mm:ss | LEVEL | module:function:line - message
        # Или: YYYY-MM-DD HH:mm:ss | LEVEL | module | message
        pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*\|\s*(\w+)\s*\|\s*([^|]+?)(?:\s*-\s*|\s*\|\s*)(.+)"
        match = re.match(pattern, line)

        if match:
            time_str, level, module, message = match.groups()
            try:
                timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
            except:
                try:
                    timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                except:
                    timestamp = None

            return {
                "timestamp": timestamp,
                "level": level,
                "module": module.strip(),
                "message": message.strip(),
                "raw": line,
            }

        return None

    def analyze_session(
        self, log_files: List[Path], time_range: Optional[Tuple[str, str]] = None
    ) -> Tuple[SessionStats, List[Dict]]:
        """Анализ сессии"""
        stats = SessionStats()
        all_lines = []

        # Читаем все логи
        for log_file in log_files:
            lines = self.read_log_file(log_file)
            all_lines.extend(lines)

        # Парсим логи
        parsed_logs = []
        for line in all_lines:
            parsed = self.parse_log_line(line)
            if parsed:
                parsed_logs.append(parsed)

        if not parsed_logs:
            return stats, []

        # Фильтрация по времени
        if time_range:
            start_time_str, end_time_str = time_range
            start_time = datetime.strptime(start_time_str, "%H:%M:%S")
            end_time = datetime.strptime(end_time_str, "%H:%M:%S")

            filtered = []
            for log in parsed_logs:
                if log["timestamp"]:
                    log_time = log["timestamp"].time()
                    if start_time.time() <= log_time <= end_time.time():
                        filtered.append(log)
            parsed_logs = filtered

        # Временные рамки
        timestamps = [log["timestamp"] for log in parsed_logs if log["timestamp"]]
        if timestamps:
            stats.start_time = min(timestamps)
            stats.end_time = max(timestamps)
            stats.duration = stats.end_time - stats.start_time

        # Анализ по типам
        # ✅ Для отслеживания закрытых позиций и их PnL
        position_close_events = []  # Список индексов закрытий позиций
        position_pnl_map = {}  # Словарь: индекс закрытия -> PnL

        for log in parsed_logs:
            level = log["level"]
            message = log["message"]

            # Ошибки и предупреждения
            if level == "ERROR":
                stats.errors_count += 1
            elif level == "WARNING":
                stats.warnings_count += 1
            elif level == "CRITICAL":
                stats.critical_errors += 1

            # Финансы - ищем equity= (последнее значение в строке)
            # equity=1018.01 или equity рассчитан: margin=32.04 + upl=-1.74 = 30.30
            equity_matches = list(
                re.finditer(r"equity[=:]\s*([\d,]+\.?\d*)", message, re.I)
            )
            if equity_matches:
                # Берем последнее значение (после "=")
                last_match = equity_matches[-1]
                balance = float(last_match.group(1).replace(",", ""))
                if (
                    balance > 100
                ):  # Только реальные балансы (не equity позиций типа 30.30)
                    if stats.start_balance == 0:
                        stats.start_balance = balance
                    stats.end_balance = balance

            # Баланс из "equity рассчитан: margin=32.04 + upl=-1.74 = 30.30"
            # Ищем последнее число после последнего "="
            if "equity рассчитан" in message.lower():
                # Ищем паттерн "= число" в конце (последнее =)
                eq_match = re.search(r"=\s*([\d,]+\.?\d*)\s*$", message)
                if eq_match:
                    balance = float(eq_match.group(1).replace(",", ""))
                    if balance > 100:  # Только реальные балансы
                        if stats.start_balance == 0:
                            stats.start_balance = balance
                        stats.end_balance = balance

            # Ордера - "🎯 Исполнение сигнала" = размещение ордера
            if "🎯" in message and "исполнение сигнала" in message.lower():
                stats.orders_placed += 1
            # "Размещение лимитного ордера" или "Размещение рыночного ордера"
            elif (
                "размещение лимитного ордера" in message.lower()
                or "размещение рыночного ордера" in message.lower()
            ):
                stats.orders_placed += 1
            # "✅ Лимитный ордер размещен" или "✅ Рыночный ордер размещен"
            elif "✅" in message and (
                "ордер размещен" in message.lower() or "order placed" in message.lower()
            ):
                stats.orders_placed += 1
            # "✅ Рыночный ордер размещен как fallback"
            elif (
                "ордер размещен" in message.lower()
                and "fallback" not in message.lower()
            ):
                stats.orders_placed += 1
            # Исполненные ордера - "order filled" или "ордер исполнен"
            elif (
                "order filled" in message.lower()
                or "ордер исполнен" in message.lower()
                or "исполнен" in message.lower()
                and "ордер" in message.lower()
            ):
                stats.orders_filled += 1
            # Ошибки размещения
            elif "ошибка размещения" in message.lower() or (
                "order failed" in message.lower() and level == "ERROR"
            ):
                stats.orders_failed += 1
            # Отмененные ордера (из истории биржи)
            elif "отменено" in message.lower() and "ордер" in message.lower():
                stats.orders_cancelled += 1

            # Позиции - "✅ Позиция открыта" или "✅ Позиция закрыта"
            if "✅ позиция открыта" in message.lower() or (
                "✅ позиция" in message.lower() and "открыта" in message.lower()
            ):
                stats.positions_opened += 1
            elif "✅ позиция" in message.lower() and "закрыт" in message.lower():
                # Отмечаем событие закрытия позиции
                # ✅ ИСПРАВЛЕНИЕ: Используем реальный индекс в массиве parsed_logs
                idx = (
                    len(parsed_logs) - 1
                )  # Текущий индекс (мы уже добавили log в parsed_logs)
                position_close_events.append(idx)  # Сохраняем индекс в parsed_logs
                stats.positions_closed += 1
                # ✅ ИСПРАВЛЕНИЕ: Пробуем найти PnL в сообщении о закрытии
                # Новый формат: "✅ Позиция ETH-USDT закрыта по tp, PnL = +0.65 USDT"
                # Или: "✅ Позиция ETH-USDT закрыта через API, PnL = +0.65 USDT"
                # Старый формат: "✅ Позиция ETH-USDT закрыта по tp"
                pnl_match = re.search(
                    r"pnl\s*[=:]\s*([\-\+]?[\d,]+\.?\d*)\s*usdt", message, re.I
                )
                if pnl_match:
                    pnl = float(pnl_match.group(1).replace(",", ""))
                    position_pnl_map[idx] = pnl

        # ✅ ИСПРАВЛЕНИЕ: Ищем PnL в строках после закрытия позиции (в пределах 10 строк)
        # Это нужно, так как PnL может быть записан в следующей строке после закрытия
        # Находим реальные индексы закрытий в parsed_logs
        close_log_indices = []
        for i, log in enumerate(parsed_logs):
            msg = log["message"]
            if "✅ позиция" in msg.lower() and "закрыт" in msg.lower():
                close_log_indices.append(i)

        # Ищем PnL для каждого закрытия
        for close_idx in close_log_indices:
            # Пробуем найти PnL в строке закрытия
            close_msg = parsed_logs[close_idx]["message"]
            pnl_match = re.search(
                r"pnl\s*[=:]\s*([\-\+]?[\d,]+\.?\d*)\s*usdt", close_msg, re.I
            )
            if pnl_match:
                pnl = float(pnl_match.group(1).replace(",", ""))
                position_pnl_map[close_idx] = pnl
                continue

            # Ищем PnL в следующих 10 строках после закрытия
            for i in range(close_idx + 1, min(close_idx + 11, len(parsed_logs))):
                next_log = parsed_logs[i]
                next_message = next_log["message"]

                # Ищем PnL в строке "💰 Позиция" сразу после закрытия
                if (
                    "💰" in next_message
                    and "позиция" in next_message.lower()
                    and "pnl" in next_message.lower()
                ):
                    pnl_match = re.search(
                        r"pnl\s*=\s*([\-\+]?[\d,]+\.?\d*)\s*usdt", next_message, re.I
                    )
                    if pnl_match:
                        pnl = float(pnl_match.group(1).replace(",", ""))
                        position_pnl_map[close_idx] = pnl
                        break  # Нашли PnL, прекращаем поиск

        # ✅ ИСПРАВЛЕНИЕ: Считаем PnL только для закрытых позиций
        for close_idx, pnl in position_pnl_map.items():
            stats.total_pnl += pnl
            if pnl > 0:
                stats.positions_profitable += 1
            else:
                stats.positions_loss += 1

        # Сигналы - обрабатываем отдельно
        for log in parsed_logs:
            message = log["message"]
            # Сигналы - "🎯 РЕАЛЬНЫЙ СИГНАЛ" (генерирован, но еще не исполнен)
            if "🎯" in message and "реальный сигнал" in message.lower():
                stats.signals_generated += 1
            # "🎯 Исполнение сигнала" - сигнал исполнен (уже учтен в orders_placed выше)
            elif "🎯" in message and "исполнение сигнала" in message.lower():
                stats.signals_executed += 1
            # Блокировки сигналов
            elif (
                "сигналов нет" in message.lower()
                or "сигнал.*блокирован" in message.lower()
                or "пропускаем сигнал" in message.lower()
            ):
                stats.signals_blocked += 1

        # Расчеты
        if stats.start_balance > 0:
            stats.profit = stats.end_balance - stats.start_balance
            stats.profit_percent = (stats.profit / stats.start_balance) * 100

        if stats.orders_placed > 0:
            stats.order_effectiveness = (
                stats.orders_filled / stats.orders_placed
            ) * 100

        # ✅ ИСПРАВЛЕНИЕ: Средний PnL считаем только по закрытым позициям
        # Если позиций закрыто больше 0, но total_pnl = 0, значит PnL не был найден в логах
        if stats.positions_closed > 0:
            stats.avg_pnl = stats.total_pnl / stats.positions_closed
        else:
            # Если позиций закрыто 0, но есть PnL - значит считались промежуточные значения (неправильно!)
            # В этом случае обнуляем неправильные данные
            if stats.total_pnl != 0 and (
                stats.positions_profitable > 0 or stats.positions_loss > 0
            ):
                # Это значит мы считали промежуточные PnL, а не финальные при закрытии
                # Обнуляем неправильные данные
                stats.total_pnl = 0.0
                stats.positions_profitable = 0
                stats.positions_loss = 0
                stats.avg_pnl = 0.0

        return stats, parsed_logs

    def compare_sessions(self, session1: SessionStats, session2: SessionStats) -> Dict:
        """Сравнение двух сессий"""
        comparison = {
            "profit_change": session2.profit - session1.profit,
            "profit_percent_change": session2.profit_percent - session1.profit_percent,
            "orders_placed_change": session2.orders_placed - session1.orders_placed,
            "order_effectiveness_change": session2.order_effectiveness
            - session1.order_effectiveness,
            "positions_opened_change": session2.positions_opened
            - session1.positions_opened,
            "errors_change": session2.errors_count - session1.errors_count,
        }

        # Анализ улучшений/ухудшений
        improvements = []
        deteriorations = []

        if comparison["profit_change"] > 0:
            improvements.append(f"Прибыль: +${comparison['profit_change']:.2f}")
        elif comparison["profit_change"] < 0:
            deteriorations.append(f"Прибыль: ${comparison['profit_change']:.2f}")

        if comparison["order_effectiveness_change"] > 0:
            improvements.append(
                f"Эффективность ордеров: +{comparison['order_effectiveness_change']:.1f}%"
            )
        elif comparison["order_effectiveness_change"] < 0:
            deteriorations.append(
                f"Эффективность ордеров: {comparison['order_effectiveness_change']:.1f}%"
            )

        if comparison["errors_change"] < 0:
            improvements.append(f"Ошибок меньше: {comparison['errors_change']}")
        elif comparison["errors_change"] > 0:
            deteriorations.append(f"Ошибок больше: +{comparison['errors_change']}")

        comparison["improvements"] = improvements
        comparison["deteriorations"] = deteriorations

        return comparison

    def generate_charts(
        self,
        stats: SessionStats,
        parsed_logs: List[Dict],
        output_dir: Path,
        report_id: Optional[str] = None,
    ):
        """Генерация графиков

        Args:
            stats: Статистика сессии
            parsed_logs: Распарсенные логи
            output_dir: Директория для сохранения
            report_id: Уникальный ID отчета (дата или дата+время) для избежания перезаписи
        """
        if not MATPLOTLIB_AVAILABLE:
            print("⚠️ Matplotlib недоступен, графики не созданы")
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        # Создаем уникальный ID для графиков (чтобы не перезаписывать)
        if report_id is None:
            if stats.start_time:
                report_id = stats.start_time.strftime("%Y-%m-%d_%H-%M-%S")
            else:
                report_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # График баланса
        balance_data = []
        balance_times = []
        for log in parsed_logs:
            message = log["message"]
            equity_matches = list(
                re.finditer(r"equity[=:]\s*([\d,]+\.?\d*)", message, re.I)
            )
            if equity_matches:
                last_match = equity_matches[-1]
                balance = float(last_match.group(1).replace(",", ""))
                if balance > 100 and log["timestamp"]:
                    balance_data.append(balance)
                    balance_times.append(log["timestamp"])

        if balance_data:
            plt.figure(figsize=(12, 6))
            plt.plot(balance_times, balance_data, "b-", linewidth=2, label="Баланс")
            plt.axhline(
                y=stats.start_balance,
                color="g",
                linestyle="--",
                alpha=0.7,
                label=f"Начальный: ${stats.start_balance:.2f}",
            )
            plt.axhline(
                y=stats.end_balance,
                color="r",
                linestyle="--",
                alpha=0.7,
                label=f"Конечный: ${stats.end_balance:.2f}",
            )
            plt.xlabel("Время")
            plt.ylabel("Баланс (USDT)")
            plt.title("Изменение баланса за сессию")
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            chart_path = output_dir / f"balance_chart_{report_id}.png"
            plt.savefig(chart_path, dpi=150)
            plt.close()
            print(f"✅ График баланса сохранен: {chart_path}")

        # График ордеров по времени
        order_times = []
        for log in parsed_logs:
            message = log["message"]
            if (
                ("🎯" in message and "исполнение сигнала" in message.lower())
                or ("размещение" in message.lower() and "ордера" in message.lower())
                or ("ордер размещен" in message.lower())
            ):
                if log["timestamp"]:
                    order_times.append(log["timestamp"])

        if order_times:
            plt.figure(figsize=(12, 6))
            # Группируем по минутам
            order_counts = Counter(
                [t.replace(second=0, microsecond=0) for t in order_times]
            )
            times = sorted(order_counts.keys())
            counts = [order_counts[t] for t in times]
            if len(times) > 1:
                # Используем timedelta для ширины баров
                width = (
                    (times[1] - times[0]) if len(times) > 1 else timedelta(minutes=1)
                )
                plt.bar(times, counts, width=width, color="orange", alpha=0.7)
            else:
                plt.bar(times, counts, color="orange", alpha=0.7)
            plt.xlabel("Время")
            plt.ylabel("Количество ордеров")
            plt.title(f"Ордера по времени (всего: {len(order_times)})")
            plt.xticks(rotation=45)
            plt.tight_layout()
            chart_path = output_dir / f"orders_chart_{report_id}.png"
            plt.savefig(chart_path, dpi=150)
            plt.close()
            print(f"✅ График ордеров сохранен: {chart_path}")

        print(f"📊 Графики сохранены в {output_dir}")

    def generate_html_report(
        self, stats: SessionStats, output_path: Path, report_id: Optional[str] = None
    ):
        """Генерация HTML отчета

        Args:
            stats: Статистика сессии
            output_path: Путь для сохранения HTML отчета
            report_id: Уникальный ID отчета (для поиска графиков)
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        profit_class = "positive" if stats.profit > 0 else "negative"
        profit_sign = "+" if stats.profit > 0 else ""
        duration_str = str(stats.duration).split(".")[0] if stats.duration else "N/A"

        # Определяем ID отчета для поиска графиков
        if report_id is None:
            if stats.start_time:
                report_id = stats.start_time.strftime("%Y-%m-%d_%H-%M-%S")
            else:
                report_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Проверяем наличие графиков с этим ID
        charts_dir = output_path.parent / "charts"
        balance_chart_path = charts_dir / f"balance_chart_{report_id}.png"
        orders_chart_path = charts_dir / f"orders_chart_{report_id}.png"

        balance_chart = (
            f"charts/balance_chart_{report_id}.png"
            if balance_chart_path.exists()
            else None
        )
        orders_chart = (
            f"charts/orders_chart_{report_id}.png"
            if orders_chart_path.exists()
            else None
        )

        html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Отчет по сессии - {stats.start_time.strftime('%Y-%m-%d') if stats.start_time else 'N/A'}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin: 20px 0; }}
        .stat-card {{ background: #f9f9f9; padding: 20px; border-radius: 5px; border-left: 4px solid #4CAF50; }}
        .stat-label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 1px; }}
        .stat-value {{ font-size: 28px; font-weight: bold; color: #333; margin-top: 5px; }}
        .positive {{ color: #4CAF50; }}
        .negative {{ color: #f44336; }}
        .section {{ margin: 30px 0; }}
        .info-row {{ display: flex; justify-content: space-between; padding: 10px; background: #f9f9f9; margin: 5px 0; border-radius: 3px; }}
        .info-label {{ font-weight: bold; color: #555; }}
        .info-value {{ color: #333; }}
        .chart {{ margin: 20px 0; text-align: center; }}
        .chart img {{ max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        table th, table td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        table th {{ background: #4CAF50; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Отчет по сессии торгового бота</h1>
        
        <div class="section">
            <h2>Временные рамки</h2>
            <div class="info-row">
                <span class="info-label">Начало:</span>
                <span class="info-value">{stats.start_time.strftime('%Y-%m-%d %H:%M:%S') if stats.start_time else 'N/A'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Конец:</span>
                <span class="info-value">{stats.end_time.strftime('%Y-%m-%d %H:%M:%S') if stats.end_time else 'N/A'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">Длительность:</span>
                <span class="info-value">{duration_str}</span>
            </div>
        </div>
        
        <div class="section">
            <h2>💰 Финансовые показатели</h2>
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-label">Начальный баланс</div>
                    <div class="stat-value">${stats.start_balance:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Конечный баланс</div>
                    <div class="stat-value">${stats.end_balance:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Прибыль/Убыток</div>
                    <div class="stat-value {profit_class}">${profit_sign}{stats.profit:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Прибыль (%)</div>
                    <div class="stat-value {profit_class}">{profit_sign}{stats.profit_percent:.2f}%</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>📈 Ордера</h2>
            <table>
                <tr>
                    <th>Метрика</th>
                    <th>Значение</th>
                </tr>
                <tr>
                    <td>Размещено</td>
                    <td>{stats.orders_placed}</td>
                </tr>
                <tr>
                    <td>Исполнено</td>
                    <td>{stats.orders_filled}</td>
                </tr>
                <tr>
                    <td>Отменено</td>
                    <td>{stats.orders_cancelled}</td>
                </tr>
                <tr>
                    <td>Ошибки</td>
                    <td>{stats.orders_failed}</td>
                </tr>
                <tr>
                    <td>Эффективность</td>
                    <td>{stats.order_effectiveness:.1f}%</td>
                </tr>
            </table>
        </div>
        
        <div class="section">
            <h2>🎯 Позиции</h2>
            <table>
                <tr>
                    <th>Метрика</th>
                    <th>Значение</th>
                </tr>
                <tr>
                    <td>Открыто</td>
                    <td>{stats.positions_opened}</td>
                </tr>
                <tr>
                    <td>Закрыто</td>
                    <td>{stats.positions_closed}</td>
                </tr>
                <tr>
                    <td>Прибыльных</td>
                    <td class="positive">{stats.positions_profitable}</td>
                </tr>
                <tr>
                    <td>Убыточных</td>
                    <td class="negative">{stats.positions_loss}</td>
                </tr>
                <tr>
                    <td>Общий PnL</td>
                    <td class="{'positive' if stats.total_pnl > 0 else 'negative'}">${stats.total_pnl:.2f}</td>
                </tr>
                <tr>
                    <td>Средний PnL</td>
                    <td class="{'positive' if stats.avg_pnl > 0 else 'negative'}">${stats.avg_pnl:.2f}</td>
                </tr>
            </table>
        </div>
        
        <div class="section">
            <h2>⚠️ Ошибки и предупреждения</h2>
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-label">Ошибки (ERROR)</div>
                    <div class="stat-value negative">{stats.errors_count}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Предупреждения (WARNING)</div>
                    <div class="stat-value">{stats.warnings_count}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Критические (CRITICAL)</div>
                    <div class="stat-value negative">{stats.critical_errors}</div>
                </div>
            </div>
        </div>
        
        {f'<div class="section"><h2>📉 Графики</h2><div class="chart"><h3>График баланса</h3><img src="{balance_chart}" alt="График баланса"></div></div>' if balance_chart else ''}
        {f'<div class="chart"><h3>График ордеров</h3><img src="{orders_chart}" alt="График ордеров"></div>' if orders_chart else ''}
        
        <div class="section">
            <p style="color: #666; font-size: 12px; text-align: center; margin-top: 40px;">
                Отчет сгенерирован: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </p>
        </div>
    </div>
</body>
</html>
        """

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_template)

        print(f"✅ HTML отчет сохранен: {output_path}")


def interactive_menu():
    """Интерактивное меню"""
    analyzer = LogAnalyzer()

    while True:
        print("\n" + "=" * 50)
        print("=== АНАЛИЗ ЛОГОВ ТОРГОВОГО БОТА ===")
        print("=" * 50)
        print("\n1. 📊 Быстрый анализ последней сессии")
        print("2. 📅 Анализ по дате")
        print("3. ⏰ Анализ по времени (диапазон)")
        print("4. 💰 Финансовая статистика")
        print("5. 📈 Ордера (размещено, исполнено, отменено)")
        print("6. ⚠️  Ошибки и предупреждения")
        print("7. 🎯 Позиции (открыто, закрыто, PnL)")
        print("8. 🔍 Поиск по паттернам")
        print("9. 📉 Графики (баланс, прибыль, ордера)")
        print("10. 📄 Полный отчет (HTML с графиками)")
        print("11. 🔄 Сравнение сессий")
        print("0. Выход")

        choice = input("\nВыберите опцию: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            quick_analysis(analyzer)
        elif choice == "2":
            date_analysis(analyzer)
        elif choice == "3":
            time_range_analysis(analyzer)
        elif choice == "4":
            financial_stats(analyzer)
        elif choice == "5":
            orders_stats(analyzer)
        elif choice == "6":
            errors_stats(analyzer)
        elif choice == "7":
            positions_stats(analyzer)
        elif choice == "8":
            search_patterns(analyzer)
        elif choice == "9":
            generate_charts_menu(analyzer)
        elif choice == "10":
            full_report(analyzer)
        elif choice == "11":
            compare_sessions_menu(analyzer)

        input("\nНажмите Enter для продолжения...")


def quick_analysis(analyzer: LogAnalyzer):
    """Быстрый анализ"""
    print("\n📊 Быстрый анализ последней сессии...")
    # Анализируем все файлы за сегодня
    today = datetime.now().strftime("%Y-%m-%d")
    log_files = analyzer.find_log_files(date=today)

    # Если за сегодня нет файлов, берем все последние файлы
    if not log_files:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Найдено файлов: {len(log_files)}")
    print(f"Обработка всех файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)  # ✅ Все файлы!

    print(f"\n📊 Результаты:")
    print(f"Время: {stats.start_time} - {stats.end_time}")
    print(f"Баланс: ${stats.start_balance:.2f} → ${stats.end_balance:.2f}")
    print(f"Прибыль: ${stats.profit:.2f} ({stats.profit_percent:.2f}%)")
    print(
        f"Ордера: размещено={stats.orders_placed}, исполнено={stats.orders_filled}, эффективность={stats.order_effectiveness:.1f}%"
    )
    print(
        f"Позиции: открыто={stats.positions_opened}, закрыто={stats.positions_closed}"
    )
    print(f"Ошибки: {stats.errors_count}, предупреждения: {stats.warnings_count}")


def date_analysis(analyzer: LogAnalyzer):
    """Анализ по дате"""
    date = input("Введите дату (YYYY-MM-DD): ").strip()
    log_files = analyzer.find_log_files(date=date)

    if not log_files:
        print(f"❌ Лог файлы за {date} не найдены")
        return

    print(f"Найдено файлов: {len(log_files)}")
    print(f"Обработка всех файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)  # ✅ Все файлы за дату!

    print(f"\n📊 Результаты за {date}:")
    print(f"Баланс: ${stats.start_balance:.2f} → ${stats.end_balance:.2f}")
    print(f"Прибыль: ${stats.profit:.2f} ({stats.profit_percent:.2f}%)")


def time_range_analysis(analyzer: LogAnalyzer):
    """Анализ по времени"""
    print("\n⏰ Анализ по времени (диапазон)")
    date = input("Дата (YYYY-MM-DD, Enter для сегодня): ").strip()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    start_time = input("Начальное время (HH:MM:SS): ").strip()
    end_time = input("Конечное время (HH:MM:SS): ").strip()

    log_files = analyzer.find_log_files(date=date)
    if not log_files:
        print(f"❌ Лог файлы за {date} не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(
        log_files, time_range=(start_time, end_time)
    )  # ✅ Все файлы за дату!

    print(f"\n📊 Результаты за {date} ({start_time} - {end_time}):")
    print(f"Баланс: ${stats.start_balance:.2f} → ${stats.end_balance:.2f}")
    print(f"Прибыль: ${stats.profit:.2f} ({stats.profit_percent:.2f}%)")
    print(f"Ордера: размещено={stats.orders_placed}, исполнено={stats.orders_filled}")
    print(
        f"Позиции: открыто={stats.positions_opened}, закрыто={stats.positions_closed}"
    )


def financial_stats(analyzer: LogAnalyzer):
    """Финансовая статистика"""
    print("\n💰 Финансовая статистика")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
    else:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)  # ✅ Все файлы!

    print(f"\n💰 Финансовая статистика:")
    print(f"Начальный баланс: ${stats.start_balance:.2f}")
    print(f"Конечный баланс: ${stats.end_balance:.2f}")
    print(f"Прибыль/Убыток: ${stats.profit:.2f} ({stats.profit_percent:+.2f}%)")
    print(f"Комиссии: ${stats.commissions:.2f}")
    print(f"Общий PnL позиций: ${stats.total_pnl:.2f}")
    print(f"Средний PnL на позицию: ${stats.avg_pnl:.2f}")


def orders_stats(analyzer: LogAnalyzer):
    """Статистика по ордерам"""
    print("\n📈 Статистика по ордерам")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
    else:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)  # ✅ Все файлы!

    print(f"\n📈 Статистика по ордерам:")
    print(f"Размещено: {stats.orders_placed}")
    print(f"Исполнено: {stats.orders_filled}")
    print(f"Отменено: {stats.orders_cancelled}")
    print(f"Ошибки: {stats.orders_failed}")
    print(f"Эффективность: {stats.order_effectiveness:.1f}%")


def errors_stats(analyzer: LogAnalyzer):
    """Статистика по ошибкам"""
    print("\n⚠️ Статистика по ошибкам")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
    else:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)  # ✅ Все файлы!

    print(f"\n⚠️ Статистика по ошибкам:")
    print(f"Ошибки (ERROR): {stats.errors_count}")
    print(f"Предупреждения (WARNING): {stats.warnings_count}")
    print(f"Критические ошибки (CRITICAL): {stats.critical_errors}")

    # Показываем примеры ошибок
    error_logs = [log for log in parsed_logs if log["level"] in ["ERROR", "CRITICAL"]]
    if error_logs:
        print(f"\nПримеры ошибок (первые 5):")
        for i, log in enumerate(error_logs[:5], 1):
            print(f"{i}. [{log['timestamp']}] {log['message'][:100]}")


def positions_stats(analyzer: LogAnalyzer):
    """Статистика по позициям"""
    print("\n🎯 Статистика по позициям")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
    else:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)  # ✅ Все файлы!

    print(f"\n🎯 Статистика по позициям:")
    print(f"Открыто: {stats.positions_opened}")
    print(f"Закрыто: {stats.positions_closed}")
    print(f"Прибыльных: {stats.positions_profitable}")
    print(f"Убыточных: {stats.positions_loss}")
    print(f"Общий PnL: ${stats.total_pnl:.2f}")
    print(f"Средний PnL: ${stats.avg_pnl:.2f}")


def search_patterns(analyzer: LogAnalyzer):
    """Поиск по паттернам"""
    print("\n🔍 Поиск по паттернам")
    pattern = input("Введите паттерн для поиска: ").strip()
    level = (
        input("Уровень лога (DEBUG/INFO/WARNING/ERROR/CRITICAL, Enter для всех): ")
        .strip()
        .upper()
    )

    log_files = analyzer.find_log_files()
    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    all_lines = []
    print(f"Обработка {len(log_files)} файлов...")
    for log_file in log_files:  # ✅ Все файлы!
        lines = analyzer.read_log_file(log_file)
        all_lines.extend(lines)

    found = []
    for line in all_lines:
        parsed = analyzer.parse_log_line(line)
        if parsed:
            if pattern.lower() in parsed["message"].lower():
                if not level or parsed["level"] == level:
                    found.append(parsed)

    print(f"\n🔍 Найдено совпадений: {len(found)}")
    if found:
        print("\nПервые 20 результатов:")
        for i, log in enumerate(found[:20], 1):
            print(f"{i}. [{log['timestamp']}] [{log['level']}] {log['message'][:150]}")


def generate_charts_menu(analyzer: LogAnalyzer):
    """Генерация графиков"""
    print("\n📉 Генерация графиков")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
    else:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)  # ✅ Все файлы!

    # Создаем уникальный ID для отчета
    report_id = (
        stats.start_time.strftime("%Y-%m-%d_%H-%M-%S")
        if stats.start_time
        else datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    )

    output_dir = Path("logs/reports/charts")
    analyzer.generate_charts(stats, parsed_logs, output_dir, report_id=report_id)
    print(f"\n✅ Графики сохранены в {output_dir} (ID: {report_id})")


def full_report(analyzer: LogAnalyzer):
    """Полный отчет с графиками"""
    print("\n📄 Полный отчет (HTML с графиками)")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
    else:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)  # ✅ Все файлы!

    # Создаем уникальный ID для отчета (дата + время)
    if stats.start_time:
        report_id = stats.start_time.strftime("%Y-%m-%d_%H-%M-%S")
        report_date = stats.start_time.strftime("%Y-%m-%d")
    else:
        report_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_date = date or datetime.now().strftime("%Y-%m-%d")

    # Генерируем графики
    output_dir = Path("logs/reports/charts")
    analyzer.generate_charts(stats, parsed_logs, output_dir, report_id=report_id)

    # Генерируем HTML отчет с уникальным именем
    report_path = Path("logs/reports") / f"report_{report_id}.html"
    analyzer.generate_html_report(stats, report_path, report_id=report_id)

    print(f"\n✅ Полный отчет сохранен: {report_path}")
    print(f"📊 Графики сохранены с ID: {report_id}")


def compare_sessions_menu(analyzer: LogAnalyzer):
    """Меню сравнения сессий"""
    print("\n🔄 Сравнение сессий")
    date1 = input("Дата первой сессии (YYYY-MM-DD): ").strip()
    date2 = input("Дата второй сессии (YYYY-MM-DD): ").strip()

    files1 = analyzer.find_log_files(date=date1)
    files2 = analyzer.find_log_files(date=date2)

    if not files1 or not files2:
        print("❌ Не найдены файлы для одной из сессий")
        return

    stats1, _ = analyzer.analyze_session(files1)
    stats2, _ = analyzer.analyze_session(files2)

    comparison = analyzer.compare_sessions(stats1, stats2)

    print("\n📊 Сравнение:")
    print(
        f"Прибыль: {comparison['profit_change']:+.2f} ({comparison['profit_percent_change']:+.2f}%)"
    )
    print(f"Эффективность ордеров: {comparison['order_effectiveness_change']:+.1f}%")

    if comparison["improvements"]:
        print("\n✅ Улучшения:")
        for imp in comparison["improvements"]:
            print(f"  + {imp}")

    if comparison["deteriorations"]:
        print("\n❌ Ухудшения:")
        for det in comparison["deteriorations"]:
            print(f"  - {det}")


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(description="Анализатор логов торгового бота")
    parser.add_argument("--quick", action="store_true", help="Быстрый анализ")
    parser.add_argument("--date", type=str, help="Анализ по дате (YYYY-MM-DD)")
    parser.add_argument(
        "--compare", nargs=2, metavar=("DATE1", "DATE2"), help="Сравнение сессий"
    )
    parser.add_argument("--output", type=str, help="Путь для сохранения отчета")

    args = parser.parse_args()

    analyzer = LogAnalyzer()

    if args.quick:
        quick_analysis(analyzer)
    elif args.date:
        log_files = analyzer.find_log_files(date=args.date)
        stats, _ = analyzer.analyze_session(log_files)
        print(f"📊 Анализ за {args.date}:")
        print(f"Прибыль: ${stats.profit:.2f}")
    elif args.compare:
        files1 = analyzer.find_log_files(date=args.compare[0])
        files2 = analyzer.find_log_files(date=args.compare[1])
        stats1, _ = analyzer.analyze_session(files1)
        stats2, _ = analyzer.analyze_session(files2)
        comparison = analyzer.compare_sessions(stats1, stats2)
        print(f"Сравнение: {comparison}")
    else:
        # Интерактивное меню
        interactive_menu()


if __name__ == "__main__":
    main()
