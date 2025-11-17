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
            # ✅ ИСПРАВЛЕНО: Рекурсивный поиск в подпапках
            for subdir in futures_dir.iterdir():
                if (
                    subdir.is_dir() and subdir.name != "archived"
                ):  # Пропускаем archived (обрабатывается отдельно)
                    for nested_log in subdir.glob("*.log"):
                        if not nested_log.is_file():
                            continue
                        log_files.append(nested_log)

            # Ищем .zip архивы в корне
            for zip_file in futures_dir.glob("*.zip"):
                log_files.append(zip_file)

            # ✅ ИСПРАВЛЕНО: Ищем .zip архивы и .log файлы в папке archived (включая подпапки)
            archived_dir = futures_dir / "archived"
            if archived_dir.exists():
                # Ищем .zip архивы в корне archived
                for zip_file in archived_dir.glob("*.zip"):
                    log_files.append(zip_file)

                # Ищем .zip архивы и .log файлы в подпапках archived (рекурсивно)
                for subdir in archived_dir.iterdir():
                    if subdir.is_dir():
                        # Логи в подпапках (из clean_logs.bat)
                        for log_file in subdir.glob("*.log"):
                            if log_file.is_file():
                                log_files.append(log_file)

                        # ZIP архивы в подпапках
                        for zip_file in subdir.glob("*.zip"):
                            if zip_file.is_file():
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

    def find_sessions(self) -> Dict[str, List[Path]]:
        """✅ НОВОЕ: Находит все сессии в архиве и группирует их по папкам/датам

        Returns:
            Dict[str, List[Path]]: {session_name: [log_files]}
        """
        sessions = {}
        futures_dir = self.logs_dir / "futures"
        archived_dir = futures_dir / "archived"

        if not archived_dir.exists():
            return sessions

        # Ищем сессии в подпапках archived (из clean_logs.bat)
        # Формат папки: logs_YYYY-MM-DD_HH-MM-SS
        for subdir in archived_dir.iterdir():
            if subdir.is_dir():
                session_name = subdir.name
                session_files = []

                # Собираем все логи и ZIP в этой папке
                for log_file in subdir.glob("*.log"):
                    if log_file.is_file():
                        session_files.append(log_file)

                for zip_file in subdir.glob("*.zip"):
                    if zip_file.is_file():
                        session_files.append(zip_file)

                if session_files:
                    sessions[session_name] = sorted(
                        session_files, key=lambda x: x.stat().st_mtime
                    )

        # Также группируем логи по датам (для логов не в папках)
        # Это для логов в корне или в других местах
        all_logs = self.find_log_files()
        logs_by_date = defaultdict(list)

        for log_file in all_logs:
            # Пропускаем логи, которые уже в сессиях
            in_session = False
            for session_files in sessions.values():
                if log_file in session_files:
                    in_session = True
                    break

            if not in_session:
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

        # Добавляем сессии по датам
        for date, files in logs_by_date.items():
            if files:
                session_name = f"Сессия {date}"
                if session_name not in sessions:
                    sessions[session_name] = sorted(
                        files, key=lambda x: x.stat().st_mtime
                    )
                else:
                    # Объединяем с существующей сессией
                    sessions[session_name].extend(files)
                    sessions[session_name] = sorted(
                        set(sessions[session_name]), key=lambda x: x.stat().st_mtime
                    )

        return sessions

    def read_log_file(self, log_file: Path) -> List[str]:
        """Чтение лог файла (поддерживает zip)

        ✅ ИСПРАВЛЕНО: Правильно читает логи из архивов, включая архивы с несколькими файлами (лог + сделки)
        """
        lines = []

        try:
            if log_file.suffix == ".zip":
                # Читаем из архива
                with zipfile.ZipFile(log_file, "r") as zip_ref:
                    # Получаем список файлов в архиве
                    file_list = zip_ref.namelist()

                    # ✅ ИСПРАВЛЕНО: Ищем .log файл в архиве (может быть несколько файлов: лог + JSON/CSV сделки)
                    log_files_in_zip = [
                        f
                        for f in file_list
                        if f.endswith(".log")
                        and not f.endswith(".csv")
                        and not f.endswith(".json")
                    ]

                    if log_files_in_zip:
                        # ✅ Приоритет: читаем .log файл (не JSON/CSV сделки)
                        # Если несколько .log файлов - выбираем тот, который соответствует имени архива
                        if len(log_files_in_zip) == 1:
                            log_to_read = log_files_in_zip[0]
                        else:
                            # Если несколько .log файлов, выбираем тот, который похож на имя архива
                            archive_name = log_file.stem  # без .zip
                            matching_logs = [
                                f
                                for f in log_files_in_zip
                                if archive_name in f or f.startswith("futures_main")
                            ]
                            log_to_read = (
                                matching_logs[0]
                                if matching_logs
                                else log_files_in_zip[0]
                            )

                        with zip_ref.open(log_to_read) as f:
                            lines = (
                                f.read().decode("utf-8", errors="ignore").splitlines()
                            )
                    elif file_list:
                        # Fallback: если нет .log файла, читаем первый файл (не JSON/CSV)
                        non_data_files = [
                            f
                            for f in file_list
                            if not f.endswith(".json") and not f.endswith(".csv")
                        ]
                        if non_data_files:
                            with zip_ref.open(non_data_files[0]) as f:
                                lines = (
                                    f.read()
                                    .decode("utf-8", errors="ignore")
                                    .splitlines()
                                )
                        else:
                            # Если только JSON/CSV - это не лог файл
                            print(
                                f"⚠️ В архиве {log_file.name} нет .log файлов, только данные (JSON/CSV)"
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
        # ✅ ИСПРАВЛЕНО: Более гибкий паттерн для разных форматов
        # Формат 1: YYYY-MM-DD HH:mm:ss | LEVEL | module:function:line - message
        # Формат 2: YYYY-MM-DD HH:mm:ss | LEVEL | module | message
        # Формат 3: YYYY-MM-DD HH:mm:ss | LEVEL | module - message (без двоеточий)

        # Сначала пробуем паттерн с "-" (наиболее частый)
        pattern1 = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*\|\s*(\w+)\s*\|\s*([^-|]+?)\s*-\s*(.+)"
        match = re.match(pattern1, line)

        if not match:
            # Пробуем паттерн с "|" (реже)
            pattern2 = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*\|\s*(\w+)\s*\|\s*([^|]+?)\s*\|\s*(.+)"
            match = re.match(pattern2, line)

        if match:
            time_str, level, module, message = match.groups()

            # Парсинг времени - пробуем разные форматы
            timestamp = None
            for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
                try:
                    timestamp = datetime.strptime(time_str, fmt)
                    break
                except:
                    continue

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

    def export_trades_to_json(
        self, parsed_logs: List[Dict], output_path: Optional[Path] = None
    ) -> Path:
        """✅ НОВОЕ: Экспорт сделок в JSON

        Args:
            parsed_logs: Распарсенные логи
            output_path: Путь для сохранения JSON (если не указан, используется logs/trades_YYYY-MM-DD.json)

        Returns:
            Путь к сохраненному файлу
        """
        if output_path is None:
            today = datetime.now().strftime("%Y-%m-%d")
            output_path = self.logs_dir / f"trades_{today}.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        trades = []
        open_positions = (
            {}
        )  # symbol -> {side, entry_price, size, timestamp, entry_log_idx}

        for i, log in enumerate(parsed_logs):
            message = log["message"]
            timestamp = log["timestamp"]

            # Открытие позиции
            if "✅ позиция" in message.lower() and "открыт" in message.lower():
                # Парсим: "✅ Позиция BTC-USDT LONG открыта по реальному сигналу"
                # Или: "✅ Рыночный ордер исполнен, позиция открыта: BTC-USDT 0.0013"
                match = re.search(
                    r"✅ (?:позиция|рыночный ордер|лимитный ордер).*?(\w+-\w+).*?(?:(\w+)\s+открыт|открыта:\s*(\w+-\w+))",
                    message,
                    re.I,
                )
                if match:
                    symbol = match.group(1) or match.group(3)
                    side_str = match.group(2) if match.group(2) else None

                    # Определяем side
                    if side_str:
                        side = (
                            "long"
                            if side_str.upper() == "LONG"
                            else "short"
                            if side_str.upper() == "SHORT"
                            else None
                        )
                    else:
                        # Пробуем найти side в сообщении
                        side_match = re.search(
                            r"(long|short|long|short)", message, re.I
                        )
                        side = side_match.group(1).lower() if side_match else None

                    # Ищем entry price, size
                    entry_match = re.search(
                        r"entry[=:]\s*([\d.]+)|price[=:]\s*([\d.]+)", message, re.I
                    )
                    size_match = re.search(
                        r"size[=:]\s*([\d.]+)|\s+([\d.]+)\s*(?:контракт|contract)",
                        message,
                        re.I,
                    )

                    open_positions[symbol] = {
                        "side": side or "long",  # По умолчанию long
                        "entry_price": float(
                            entry_match.group(1) or entry_match.group(2)
                        )
                        if entry_match
                        else None,
                        "size": float(size_match.group(1) or size_match.group(2))
                        if size_match
                        else None,
                        "timestamp": timestamp,
                        "entry_log_idx": i,
                    }

            # Закрытие позиции
            elif "✅ позиция" in message.lower() and "закрыт" in message.lower():
                # Парсим: "✅ Позиция BTC-USDT закрыта по tp, PnL = +0.65 USDT"
                match = re.search(r"✅ позиция\s+(\w+-\w+)\s+закрыт", message, re.I)
                if match:
                    symbol = match.group(1)

                    if symbol in open_positions:
                        pos = open_positions[symbol]

                        # Ищем exit price, PnL, reason
                        exit_match = re.search(
                            r"exit[=:]\s*([\d.]+)|price[=:]\s*([\d.]+)", message, re.I
                        )
                        pnl_match = re.search(
                            r"pnl\s*[=:]\s*([\-\+]?[\d,]+\.?\d*)\s*usdt", message, re.I
                        )
                        reason_match = re.search(
                            r"закрыт\s+(?:по|через)\s+(\w+)", message, re.I
                        )

                        # Ищем PnL в следующих строках, если не найден
                        if not pnl_match and i + 1 < len(parsed_logs):
                            for j in range(i + 1, min(i + 11, len(parsed_logs))):
                                next_msg = parsed_logs[j]["message"]
                                pnl_match = re.search(
                                    r"pnl\s*[=:]\s*([\-\+]?[\d,]+\.?\d*)\s*usdt",
                                    next_msg,
                                    re.I,
                                )
                                if pnl_match:
                                    break

                        trade = {
                            "timestamp": pos["timestamp"].isoformat()
                            if pos["timestamp"]
                            else None,
                            "symbol": symbol,
                            "side": pos["side"],
                            "entry_price": pos["entry_price"],
                            "exit_price": float(
                                exit_match.group(1) or exit_match.group(2)
                            )
                            if exit_match
                            else None,
                            "size": pos["size"],
                            "net_pnl": float(pnl_match.group(1).replace(",", ""))
                            if pnl_match
                            else None,
                            "reason": reason_match.group(1) if reason_match else None,
                            "duration_sec": (
                                timestamp - pos["timestamp"]
                            ).total_seconds()
                            if timestamp and pos["timestamp"]
                            else None,
                            "entry_log_idx": pos["entry_log_idx"],
                            "exit_log_idx": i,
                        }

                        trades.append(trade)
                        del open_positions[symbol]

        # Сохраняем в JSON
        result = {
            "trades": trades,
            "count": len(trades),
            "open_positions": len(open_positions),
            "exported_at": datetime.now().isoformat(),
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"✅ Экспортировано {len(trades)} сделок в {output_path}")
        return output_path

    def export_trades_to_csv(
        self, parsed_logs: List[Dict], output_path: Optional[Path] = None
    ) -> Path:
        """✅ НОВОЕ: Экспорт сделок в CSV

        Args:
            parsed_logs: Распарсенные логи
            output_path: Путь для сохранения CSV (если не указан, используется logs/trades_YYYY-MM-DD.csv)

        Returns:
            Путь к сохраненному файлу
        """
        import csv

        if output_path is None:
            today = datetime.now().strftime("%Y-%m-%d")
            output_path = self.logs_dir / f"trades_{today}.csv"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Сначала получаем сделки из JSON экспорта
        json_path = output_path.with_suffix(".json")
        if json_path.exists():
            # Если JSON уже существует, используем его
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                trades = data.get("trades", [])
        else:
            # Если JSON нет, парсим логи (используем ту же логику что и в export_trades_to_json)
            trades = []
            open_positions = {}

            for i, log in enumerate(parsed_logs):
                message = log["message"]
                timestamp = log["timestamp"]

                if "✅ позиция" in message.lower() and "открыт" in message.lower():
                    match = re.search(
                        r"✅ (?:позиция|рыночный ордер|лимитный ордер).*?(\w+-\w+).*?(?:(\w+)\s+открыт|открыта:\s*(\w+-\w+))",
                        message,
                        re.I,
                    )
                    if match:
                        symbol = match.group(1) or match.group(3)
                        side_str = match.group(2) if match.group(2) else None
                        side = (
                            "long"
                            if side_str and side_str.upper() == "LONG"
                            else "short"
                            if side_str and side_str.upper() == "SHORT"
                            else None
                        )
                        if not side:
                            side_match = re.search(r"(long|short)", message, re.I)
                            side = side_match.group(1).lower() if side_match else "long"

                        entry_match = re.search(
                            r"entry[=:]\s*([\d.]+)|price[=:]\s*([\d.]+)", message, re.I
                        )
                        size_match = re.search(
                            r"size[=:]\s*([\d.]+)|\s+([\d.]+)\s*(?:контракт|contract)",
                            message,
                            re.I,
                        )

                        open_positions[symbol] = {
                            "side": side,
                            "entry_price": float(
                                entry_match.group(1) or entry_match.group(2)
                            )
                            if entry_match
                            else None,
                            "size": float(size_match.group(1) or size_match.group(2))
                            if size_match
                            else None,
                            "timestamp": timestamp,
                            "entry_log_idx": i,
                        }

                elif "✅ позиция" in message.lower() and "закрыт" in message.lower():
                    match = re.search(r"✅ позиция\s+(\w+-\w+)\s+закрыт", message, re.I)
                    if match:
                        symbol = match.group(1)
                        if symbol in open_positions:
                            pos = open_positions[symbol]
                            exit_match = re.search(
                                r"exit[=:]\s*([\d.]+)|price[=:]\s*([\d.]+)",
                                message,
                                re.I,
                            )
                            pnl_match = re.search(
                                r"pnl\s*[=:]\s*([\-\+]?[\d,]+\.?\d*)\s*usdt",
                                message,
                                re.I,
                            )
                            if not pnl_match and i + 1 < len(parsed_logs):
                                for j in range(i + 1, min(i + 11, len(parsed_logs))):
                                    next_msg = parsed_logs[j]["message"]
                                    pnl_match = re.search(
                                        r"pnl\s*[=:]\s*([\-\+]?[\d,]+\.?\d*)\s*usdt",
                                        next_msg,
                                        re.I,
                                    )
                                    if pnl_match:
                                        break

                            reason_match = re.search(
                                r"закрыт\s+(?:по|через)\s+(\w+)", message, re.I
                            )

                            trade = {
                                "timestamp": pos["timestamp"].isoformat()
                                if pos["timestamp"]
                                else None,
                                "symbol": symbol,
                                "side": pos["side"],
                                "entry_price": pos["entry_price"],
                                "exit_price": float(
                                    exit_match.group(1) or exit_match.group(2)
                                )
                                if exit_match
                                else None,
                                "size": pos["size"],
                                "net_pnl": float(pnl_match.group(1).replace(",", ""))
                                if pnl_match
                                else None,
                                "reason": reason_match.group(1)
                                if reason_match
                                else None,
                                "duration_sec": (
                                    timestamp - pos["timestamp"]
                                ).total_seconds()
                                if timestamp and pos["timestamp"]
                                else None,
                            }
                            trades.append(trade)
                            del open_positions[symbol]

        # Сохраняем в CSV
        file_exists = output_path.exists()
        with open(
            output_path, "a" if file_exists else "w", newline="", encoding="utf-8"
        ) as f:
            fieldnames = [
                "timestamp",
                "symbol",
                "side",
                "entry_price",
                "exit_price",
                "size",
                "gross_pnl",
                "commission",
                "net_pnl",
                "duration_sec",
                "reason",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            for trade in trades:
                # Рассчитываем gross_pnl и commission если нет
                if (
                    trade.get("net_pnl") is not None
                    and trade.get("entry_price")
                    and trade.get("exit_price")
                ):
                    if trade["side"] == "long":
                        gross_pnl = (trade["exit_price"] - trade["entry_price"]) * (
                            trade["size"] or 0
                        )
                    else:
                        gross_pnl = (trade["entry_price"] - trade["exit_price"]) * (
                            trade["size"] or 0
                        )
                    commission = (
                        gross_pnl - trade["net_pnl"]
                        if trade["net_pnl"] is not None
                        else 0
                    )
                else:
                    gross_pnl = None
                    commission = None

                writer.writerow(
                    {
                        "timestamp": trade.get("timestamp") or "",
                        "symbol": trade.get("symbol") or "",
                        "side": trade.get("side") or "",
                        "entry_price": f"{trade['entry_price']:.8f}"
                        if trade.get("entry_price")
                        else "",
                        "exit_price": f"{trade['exit_price']:.8f}"
                        if trade.get("exit_price")
                        else "",
                        "size": f"{trade['size']:.8f}" if trade.get("size") else "",
                        "gross_pnl": f"{gross_pnl:.4f}"
                        if gross_pnl is not None
                        else "",
                        "commission": f"{commission:.4f}"
                        if commission is not None
                        else "",
                        "net_pnl": f"{trade['net_pnl']:.4f}"
                        if trade.get("net_pnl") is not None
                        else "",
                        "duration_sec": f"{trade['duration_sec']:.0f}"
                        if trade.get("duration_sec")
                        else "",
                        "reason": trade.get("reason") or "",
                    }
                )

        print(f"✅ Экспортировано {len(trades)} сделок в {output_path}")
        return output_path

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
            "positions_closed_change": session2.positions_closed
            - session1.positions_closed,
            "positions_profitable_change": session2.positions_profitable
            - session1.positions_profitable,
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
            plt.figure(figsize=(14, 7))

            # ✅ ИСПРАВЛЕНО: Используем полный временной диапазон сессии
            if stats.start_time and stats.end_time:
                # Устанавливаем границы оси X от начала до конца сессии
                plt.xlim(stats.start_time, stats.end_time)

                # Форматирование времени в зависимости от длительности
                duration_hours = (
                    stats.end_time - stats.start_time
                ).total_seconds() / 3600
                if duration_hours > 24:
                    # Если больше суток - показываем дату и время
                    plt.gca().xaxis.set_major_formatter(
                        mdates.DateFormatter("%d.%m %H:%M")
                    )
                    plt.gca().xaxis.set_major_locator(
                        mdates.HourLocator(interval=max(1, int(duration_hours / 12)))
                    )
                elif duration_hours > 1:
                    # Если больше часа - показываем время с интервалом по часам/минутам
                    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                    if duration_hours > 6:
                        plt.gca().xaxis.set_major_locator(
                            mdates.HourLocator(interval=1)
                        )
                    else:
                        plt.gca().xaxis.set_major_locator(
                            mdates.MinuteLocator(
                                interval=max(15, int(duration_hours * 60 / 10))
                            )
                        )
                else:
                    # Если меньше часа - показываем минуты и секунды
                    plt.gca().xaxis.set_major_formatter(
                        mdates.DateFormatter("%H:%M:%S")
                    )
                    plt.gca().xaxis.set_major_locator(
                        mdates.MinuteLocator(
                            interval=max(1, int(duration_hours * 60 / 10))
                        )
                    )

            plt.plot(
                balance_times,
                balance_data,
                "b-",
                linewidth=2,
                marker="o",
                markersize=3,
                label="Баланс",
            )
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
            plt.xlabel("Время", fontsize=11)
            plt.ylabel("Баланс (USDT)", fontsize=11)

            # ✅ Добавляем информацию о временном диапазоне в заголовок
            if stats.start_time and stats.end_time:
                duration_str = (
                    str(stats.duration).split(".")[0] if stats.duration else "N/A"
                )
                plt.title(
                    f"Изменение баланса за сессию\n{stats.start_time.strftime('%Y-%m-%d %H:%M:%S')} - {stats.end_time.strftime('%H:%M:%S')} ({duration_str})",
                    fontsize=12,
                )
            else:
                plt.title("Изменение баланса за сессию", fontsize=12)

            plt.legend(loc="best", fontsize=10)
            plt.grid(True, alpha=0.3, linestyle="--")
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            chart_path = output_dir / f"balance_chart_{report_id}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches="tight")
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
            plt.figure(figsize=(14, 7))

            # ✅ ИСПРАВЛЕНО: Группируем по минутам, но учитываем весь временной диапазон
            if stats.start_time and stats.end_time:
                # Создаем временной диапазон от начала до конца сессии с шагом в 1 минуту
                start_min = stats.start_time.replace(second=0, microsecond=0)
                end_min = stats.end_time.replace(second=0, microsecond=0) + timedelta(
                    minutes=1
                )

                # Генерируем все минуты в диапазоне
                all_minutes = []
                current = start_min
                while current <= end_min:
                    all_minutes.append(current)
                    current += timedelta(minutes=1)

                # Считаем ордера по минутам
                order_counts = Counter(
                    [t.replace(second=0, microsecond=0) for t in order_times]
                )

                # Заполняем все минуты (даже те, где ордеров не было)
                times = all_minutes
                counts = [order_counts.get(t, 0) for t in all_minutes]

                # Устанавливаем границы оси X
                plt.xlim(start_min, end_min)

                # Форматирование времени
                duration_hours = (
                    stats.end_time - stats.start_time
                ).total_seconds() / 3600
                if duration_hours > 24:
                    plt.gca().xaxis.set_major_formatter(
                        mdates.DateFormatter("%d.%m %H:%M")
                    )
                    plt.gca().xaxis.set_major_locator(
                        mdates.HourLocator(interval=max(1, int(duration_hours / 12)))
                    )
                elif duration_hours > 1:
                    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                    if duration_hours > 6:
                        plt.gca().xaxis.set_major_locator(
                            mdates.HourLocator(interval=1)
                        )
                    else:
                        plt.gca().xaxis.set_major_locator(
                            mdates.MinuteLocator(
                                interval=max(15, int(duration_hours * 60 / 10))
                            )
                        )
                else:
                    plt.gca().xaxis.set_major_formatter(
                        mdates.DateFormatter("%H:%M:%S")
                    )
                    plt.gca().xaxis.set_major_locator(
                        mdates.MinuteLocator(
                            interval=max(1, int(duration_hours * 60 / 10))
                        )
                    )

                # Рисуем бары с шириной 1 минута
                width = timedelta(minutes=1)
                plt.bar(
                    times,
                    counts,
                    width=width,
                    color="orange",
                    alpha=0.7,
                    edgecolor="darkorange",
                    linewidth=0.5,
                )
            else:
                # Fallback на старую логику, если нет времени начала/конца
                order_counts = Counter(
                    [t.replace(second=0, microsecond=0) for t in order_times]
                )
                times = sorted(order_counts.keys())
                counts = [order_counts[t] for t in times]
                if len(times) > 1:
                    width = (
                        (times[1] - times[0])
                        if len(times) > 1
                        else timedelta(minutes=1)
                    )
                    plt.bar(times, counts, width=width, color="orange", alpha=0.7)
                else:
                    plt.bar(times, counts, color="orange", alpha=0.7)

            plt.xlabel("Время", fontsize=11)
            plt.ylabel("Количество ордеров", fontsize=11)

            # ✅ Добавляем информацию о временном диапазоне в заголовок
            if stats.start_time and stats.end_time:
                duration_str = (
                    str(stats.duration).split(".")[0] if stats.duration else "N/A"
                )
                plt.title(
                    f"Ордера по времени (всего: {len(order_times)})\n{stats.start_time.strftime('%Y-%m-%d %H:%M:%S')} - {stats.end_time.strftime('%H:%M:%S')} ({duration_str})",
                    fontsize=12,
                )
            else:
                plt.title(f"Ордера по времени (всего: {len(order_times)})", fontsize=12)

            plt.grid(True, alpha=0.3, linestyle="--", axis="y")
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            chart_path = output_dir / f"orders_chart_{report_id}.png"
            plt.savefig(chart_path, dpi=150, bbox_inches="tight")
            plt.close()
            print(f"✅ График ордеров сохранен: {chart_path}")

        print(f"📊 Графики сохранены в {output_dir}")

    def generate_html_report(
        self,
        stats: SessionStats,
        output_path: Path,
        report_id: Optional[str] = None,
        charts_dir: Optional[Path] = None,
    ):
        """Генерация HTML отчета

        Args:
            stats: Статистика сессии
            output_path: Путь для сохранения HTML отчета
            report_id: Уникальный ID отчета (для поиска графиков)
            charts_dir: Директория с графиками (если не указана, используется output_path.parent / "charts")
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

        # ✅ ИСПРАВЛЕНО: Используем явный путь для графиков
        if charts_dir is None:
            charts_dir = output_path.parent / "charts"

        charts_dir.mkdir(parents=True, exist_ok=True)
        balance_chart_path = charts_dir / f"balance_chart_{report_id}.png"
        orders_chart_path = charts_dir / f"orders_chart_{report_id}.png"

        # ✅ ИСПРАВЛЕНО: Правильные относительные пути для графиков
        try:
            charts_rel_dir = charts_dir.relative_to(output_path.parent)
        except (ValueError, AttributeError):
            # Если пути не относительные или is_relative_to не доступен
            charts_rel_dir = Path("charts")
        balance_chart = (
            f"{charts_rel_dir}/balance_chart_{report_id}.png"
            if balance_chart_path.exists()
            else None
        )
        orders_chart = (
            f"{charts_rel_dir}/orders_chart_{report_id}.png"
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

    def generate_investor_report(
        self,
        stats: SessionStats,
        parsed_logs: List[Dict],
        output_path: Path,
        report_id: Optional[str] = None,
        charts_dir: Optional[Path] = None,
    ):
        """✅ НОВОЕ: Генерация отчета для инвесторов (красивый HTML, упрощенный)"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if charts_dir is None:
            charts_dir = output_path.parent / "charts"

        charts_dir.mkdir(parents=True, exist_ok=True)
        balance_chart_path = charts_dir / f"balance_chart_{report_id}.png"
        orders_chart_path = charts_dir / f"orders_chart_{report_id}.png"

        try:
            charts_rel_dir = charts_dir.relative_to(output_path.parent)
        except (ValueError, AttributeError):
            charts_rel_dir = Path("charts")

        balance_chart = (
            f"{charts_rel_dir}/balance_chart_{report_id}.png"
            if balance_chart_path.exists()
            else None
        )
        orders_chart = (
            f"{charts_rel_dir}/orders_chart_{report_id}.png"
            if orders_chart_path.exists()
            else None
        )

        profit_class = "positive" if stats.profit > 0 else "negative"
        profit_sign = "+" if stats.profit > 0 else ""
        duration_str = str(stats.duration).split(".")[0] if stats.duration else "N/A"
        win_rate = (
            (stats.positions_profitable / stats.positions_closed * 100)
            if stats.positions_closed > 0
            else 0
        )

        html_template = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Инвесторский отчет - {stats.start_time.strftime('%Y-%m-%d') if stats.start_time else 'N/A'}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 15px; overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px; text-align: center; }}
        .content {{ padding: 40px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 25px; margin: 30px 0; }}
        .summary-card {{ background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); padding: 30px; border-radius: 10px; text-align: center; }}
        .summary-card .label {{ font-size: 0.9em; color: #666; text-transform: uppercase; margin-bottom: 10px; }}
        .summary-card .value {{ font-size: 2.5em; font-weight: bold; color: #333; }}
        .positive {{ color: #4CAF50 !important; }}
        .negative {{ color: #f44336 !important; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .stat-item {{ background: #f9f9f9; padding: 20px; border-radius: 8px; border-left: 4px solid #667eea; }}
        .chart {{ margin: 30px 0; text-align: center; background: #f9f9f9; padding: 20px; border-radius: 10px; }}
        .chart img {{ max-width: 100%; height: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Инвесторский отчет</h1>
            <p>Торговый бот - Анализ производительности</p>
        </div>
        <div class="content">
            <div class="summary">
                <div class="summary-card"><div class="label">Начальный баланс</div><div class="value">${stats.start_balance:.2f}</div></div>
                <div class="summary-card"><div class="label">Конечный баланс</div><div class="value">${stats.end_balance:.2f}</div></div>
                <div class="summary-card"><div class="label">Прибыль / Убыток</div><div class="value {profit_class}">{profit_sign}${stats.profit:.2f}</div></div>
                <div class="summary-card"><div class="label">Доходность</div><div class="value {profit_class}">{profit_sign}{stats.profit_percent:.2f}%</div></div>
            </div>
            <div class="stats-grid">
                <div class="stat-item"><div class="label">Длительность</div><div class="value">{duration_str}</div></div>
                <div class="stat-item"><div class="label">Всего сделок</div><div class="value">{stats.positions_closed}</div></div>
                <div class="stat-item"><div class="label">Прибыльных</div><div class="value positive">{stats.positions_profitable}</div></div>
                <div class="stat-item"><div class="label">Убыточных</div><div class="value negative">{stats.positions_loss}</div></div>
                <div class="stat-item"><div class="label">Винрейт</div><div class="value">{win_rate:.1f}%</div></div>
                <div class="stat-item"><div class="label">Средний PnL</div><div class="value {'positive' if stats.avg_pnl > 0 else 'negative'}">${stats.avg_pnl:.2f}</div></div>
            </div>
            {f'<div class="chart"><h3>Изменение баланса</h3><img src="{balance_chart}" alt="График баланса"></div>' if balance_chart else ''}
            {f'<div class="chart"><h3>Активность ордеров</h3><img src="{orders_chart}" alt="График ордеров"></div>' if orders_chart else ''}
        </div>
    </div>
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_template)

        print(f"✅ Отчет для инвесторов сохранен: {output_path}")

    def generate_developer_report(
        self,
        stats: SessionStats,
        parsed_logs: List[Dict],
        output_path: Path,
        report_id: Optional[str] = None,
        charts_dir: Optional[Path] = None,
    ):
        """✅ НОВОЕ: Генерация отчета для разработчиков (детальная информация)"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if charts_dir is None:
            charts_dir = output_path.parent / "charts"

        charts_dir.mkdir(parents=True, exist_ok=True)
        balance_chart_path = charts_dir / f"balance_chart_{report_id}.png"
        orders_chart_path = charts_dir / f"orders_chart_{report_id}.png"

        try:
            charts_rel_dir = charts_dir.relative_to(output_path.parent)
        except (ValueError, AttributeError):
            charts_rel_dir = Path("charts")

        balance_chart = (
            f"{charts_rel_dir}/balance_chart_{report_id}.png"
            if balance_chart_path.exists()
            else None
        )
        orders_chart = (
            f"{charts_rel_dir}/orders_chart_{report_id}.png"
            if orders_chart_path.exists()
            else None
        )

        error_messages = []
        signal_blocks = defaultdict(int)
        for log in parsed_logs:
            if log["level"] in ["ERROR", "CRITICAL"]:
                if len(error_messages) < 50:
                    error_messages.append(
                        {
                            "time": log["timestamp"].strftime("%H:%M:%S")
                            if log["timestamp"]
                            else "N/A",
                            "level": log["level"],
                            "message": log["message"][:200],
                            "module": log["module"][:50],
                        }
                    )
            msg = log["message"]
            if "блокирован" in msg.lower():
                if "MTF" in msg:
                    signal_blocks["MTF"] += 1
                elif "ADX" in msg:
                    signal_blocks["ADX"] += 1
                elif "liquidity" in msg.lower():
                    signal_blocks["Liquidity"] += 1
                else:
                    signal_blocks["Other"] += 1

        profit_class = "positive" if stats.profit > 0 else "negative"
        profit_sign = "+" if stats.profit > 0 else ""
        duration_str = str(stats.duration).split(".")[0] if stats.duration else "N/A"

        html_template = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Отчет для разработчиков - {stats.start_time.strftime('%Y-%m-%d') if stats.start_time else 'N/A'}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Consolas', monospace; background: #1e1e1e; color: #d4d4d4; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: #252526; border-radius: 8px; padding: 30px; }}
        h1 {{ color: #4EC9B0; margin-bottom: 20px; }}
        h2 {{ color: #569CD6; margin: 30px 0 15px 0; border-bottom: 2px solid #3e3e42; padding-bottom: 10px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .stat-card {{ background: #2d2d30; padding: 20px; border-radius: 5px; border-left: 4px solid #007ACC; }}
        .positive {{ color: #4EC9B0 !important; }}
        .negative {{ color: #F48771 !important; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: #1e1e1e; }}
        table th, table td {{ padding: 12px; text-align: left; border: 1px solid #3e3e42; }}
        table th {{ background: #007ACC; color: white; }}
        .error-log {{ background: #2d2d30; padding: 10px; margin: 5px 0; border-radius: 4px; border-left: 4px solid #F48771; }}
        .chart {{ margin: 30px 0; text-align: center; background: #1e1e1e; padding: 20px; border-radius: 8px; }}
        .chart img {{ max-width: 100%; height: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔧 Отчет для разработчиков</h1>
        <h2>📊 Общая статистика</h2>
        <div class="stats-grid">
            <div class="stat-card"><div>Начальный баланс</div><div>${stats.start_balance:.2f}</div></div>
            <div class="stat-card"><div>Конечный баланс</div><div>${stats.end_balance:.2f}</div></div>
            <div class="stat-card"><div>Прибыль</div><div class="{profit_class}">{profit_sign}${stats.profit:.2f}</div></div>
            <div class="stat-card"><div>Доходность</div><div class="{profit_class}">{profit_sign}{stats.profit_percent:.2f}%</div></div>
        </div>
        <h2>📈 Ордера</h2>
        <table>
            <tr><th>Метрика</th><th>Значение</th></tr>
            <tr><td>Размещено</td><td>{stats.orders_placed}</td></tr>
            <tr><td>Исполнено</td><td>{stats.orders_filled}</td></tr>
            <tr><td>Ошибки</td><td class="negative">{stats.orders_failed}</td></tr>
        </table>
        <h2>🎯 Позиции</h2>
        <table>
            <tr><th>Метрика</th><th>Значение</th></tr>
            <tr><td>Открыто</td><td>{stats.positions_opened}</td></tr>
            <tr><td>Закрыто</td><td>{stats.positions_closed}</td></tr>
            <tr><td>Прибыльных</td><td class="positive">{stats.positions_profitable}</td></tr>
            <tr><td>Убыточных</td><td class="negative">{stats.positions_loss}</td></tr>
        </table>
        <h2>🚫 Блокировки сигналов</h2>
        <table>
            <tr><th>Тип</th><th>Количество</th></tr>
            {''.join([f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in signal_blocks.items()])}
        </table>
        <h2>⚠️ Ошибки</h2>
        <table>
            <tr><th>Тип</th><th>Количество</th></tr>
            <tr><td>ERROR</td><td class="negative">{stats.errors_count}</td></tr>
            <tr><td>WARNING</td><td>{stats.warnings_count}</td></tr>
        </table>
        {f'<h2>🔍 Примеры ошибок</h2>' + ''.join([f'<div class="error-log">[{err["time"]}] [{err["level"]}] {err["module"]} - {err["message"]}</div>' for err in error_messages[:10]]) if error_messages else ''}
        {f'<h2>📉 Графики</h2><div class="chart"><img src="{balance_chart}" alt="График баланса"></div>' if balance_chart else ''}
        {f'<div class="chart"><img src="{orders_chart}" alt="График ордеров"></div>' if orders_chart else ''}
    </div>
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_template)

        print(f"✅ Отчет для разработчиков сохранен: {output_path}")


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
        print("12. 💼 Отчет для инвесторов (красивый HTML)")
        print("13. 🔧 Отчет для разработчиков (детальная информация)")
        print("14. 💾 Экспорт сделок в JSON")
        print("15. 📋 Экспорт сделок в CSV")
        print("16. 🗄️  Архивация логов")
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
        elif choice == "12":
            investor_report(analyzer)
        elif choice == "13":
            developer_report(analyzer)
        elif choice == "14":
            export_trades_json(analyzer)
        elif choice == "15":
            export_trades_csv(analyzer)
        elif choice == "16":
            archive_logs_menu()

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
    analyzer.generate_html_report(
        stats, report_path, report_id=report_id, charts_dir=output_dir
    )

    print(f"\n✅ Полный отчет сохранен: {report_path}")
    print(f"📊 Графики сохранены с ID: {report_id}")


def compare_sessions_menu(analyzer: LogAnalyzer):
    """✅ ИСПРАВЛЕНО: Меню сравнения сессий с интерактивным выбором"""
    print("\n🔄 Сравнение сессий")

    # ✅ НОВОЕ: Находим все сессии
    sessions = analyzer.find_sessions()

    if not sessions:
        print("❌ Сессии не найдены в архиве")
        print("💡 Подсказка: Используйте clean_logs.bat для архивации логов")
        return

    # Показываем список сессий
    print(f"\n📁 Найдено сессий: {len(sessions)}")
    print("\nДоступные сессии:")
    session_list = list(sessions.items())
    for i, (session_name, files) in enumerate(session_list, 1):
        # Определяем дату и время сессии из имени папки или файлов
        date_info = ""
        if "logs_" in session_name:
            # Формат: logs_YYYY-MM-DD_HH-MM-SS
            date_match = re.search(
                r"(\d{4}-\d{2}-\d{2})[_\s](\d{2}-\d{2}-\d{2})", session_name
            )
            if date_match:
                date_info = (
                    f" ({date_match.group(1)} {date_match.group(2).replace('-', ':')})"
                )
        elif "Сессия" in session_name:
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", session_name)
            if date_match:
                date_info = f" ({date_match.group(1)})"

        print(f"  {i}. {session_name}{date_info} ({len(files)} файл(ов))")

    # Выбор первой сессии
    print("\n" + "=" * 60)
    try:
        choice1 = input(f"\nВыберите первую сессию (1-{len(session_list)}): ").strip()
        idx1 = int(choice1) - 1
        if idx1 < 0 or idx1 >= len(session_list):
            print("❌ Неверный выбор")
            return
        session1_name, files1 = session_list[idx1]
    except (ValueError, IndexError):
        print("❌ Неверный выбор")
        return

    # Выбор второй сессии
    print("\n" + "=" * 60)
    try:
        choice2 = input(f"Выберите вторую сессию (1-{len(session_list)}): ").strip()
        idx2 = int(choice2) - 1
        if idx2 < 0 or idx2 >= len(session_list):
            print("❌ Неверный выбор")
            return
        session2_name, files2 = session_list[idx2]
    except (ValueError, IndexError):
        print("❌ Неверный выбор")
        return

    if idx1 == idx2:
        print("❌ Нельзя сравнивать сессию с самой собой")
        return

    print(f"\n📊 Анализ сессий...")
    print(f"  Сессия 1: {session1_name} ({len(files1)} файл(ов))")
    print(f"  Сессия 2: {session2_name} ({len(files2)} файл(ов))")

    # Анализируем сессии
    stats1, _ = analyzer.analyze_session(files1)
    stats2, _ = analyzer.analyze_session(files2)

    comparison = analyzer.compare_sessions(stats1, stats2)

    print("\n" + "=" * 60)
    print("📊 СРАВНЕНИЕ СЕССИЙ")
    print("=" * 60)
    print(f"\nСессия 1: {session1_name}")
    print(f"  Баланс: ${stats1.start_balance:.2f} → ${stats1.end_balance:.2f}")
    print(f"  Прибыль: ${stats1.profit:.2f} ({stats1.profit_percent:+.2f}%)")
    print(
        f"  Позиций: {stats1.positions_closed} (прибыльных: {stats1.positions_profitable})"
    )

    print(f"\nСессия 2: {session2_name}")
    print(f"  Баланс: ${stats2.start_balance:.2f} → ${stats2.end_balance:.2f}")
    print(f"  Прибыль: ${stats2.profit:.2f} ({stats2.profit_percent:+.2f}%)")
    print(
        f"  Позиций: {stats2.positions_closed} (прибыльных: {stats2.positions_profitable})"
    )

    print("\n" + "=" * 60)
    print("📈 ИЗМЕНЕНИЯ")
    print("=" * 60)
    print(
        f"Прибыль: {comparison['profit_change']:+.2f} USDT ({comparison['profit_percent_change']:+.2f}%)"
    )
    print(f"Эффективность ордеров: {comparison['order_effectiveness_change']:+.1f}%")
    print(f"Позиций закрыто: {comparison['positions_closed_change']:+d}")
    print(f"Прибыльных позиций: {comparison['positions_profitable_change']:+d}")

    if comparison["improvements"]:
        print("\n✅ Улучшения:")
        for imp in comparison["improvements"]:
            print(f"  + {imp}")

    if comparison["deteriorations"]:
        print("\n❌ Ухудшения:")
        for det in comparison["deteriorations"]:
            print(f"  - {det}")


def investor_report(analyzer: LogAnalyzer):
    """✅ НОВОЕ: Отчет для инвесторов (красивый HTML)"""
    print("\n💼 Отчет для инвесторов")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
    else:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)

    # Создаем уникальный ID для отчета
    if stats.start_time:
        report_id = stats.start_time.strftime("%Y-%m-%d_%H-%M-%S")
    else:
        report_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # Генерируем графики
    output_dir = Path("logs/reports/charts")
    analyzer.generate_charts(stats, parsed_logs, output_dir, report_id=report_id)

    # Генерируем отчет для инвесторов
    report_path = Path("logs/reports") / f"investor_report_{report_id}.html"
    analyzer.generate_investor_report(
        stats, parsed_logs, report_path, report_id=report_id, charts_dir=output_dir
    )


def developer_report(analyzer: LogAnalyzer):
    """✅ НОВОЕ: Отчет для разработчиков (детальная информация)"""
    print("\n🔧 Отчет для разработчиков")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
    else:
        log_files = analyzer.find_log_files()

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)

    # Создаем уникальный ID для отчета
    if stats.start_time:
        report_id = stats.start_time.strftime("%Y-%m-%d_%H-%M-%S")
    else:
        report_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # Генерируем графики
    output_dir = Path("logs/reports/charts")
    analyzer.generate_charts(stats, parsed_logs, output_dir, report_id=report_id)

    # Генерируем отчет для разработчиков
    report_path = Path("logs/reports") / f"developer_report_{report_id}.html"
    analyzer.generate_developer_report(
        stats, parsed_logs, report_path, report_id=report_id, charts_dir=output_dir
    )


def export_trades_json(analyzer: LogAnalyzer):
    """✅ НОВОЕ: Экспорт сделок в JSON"""
    print("\n💾 Экспорт сделок в JSON")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
        output_path = analyzer.logs_dir / f"trades_{date}.json"
    else:
        log_files = analyzer.find_log_files()
        output_path = None

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)

    json_path = analyzer.export_trades_to_json(parsed_logs, output_path)
    print(f"\n✅ Сделки экспортированы в JSON: {json_path}")


def export_trades_csv(analyzer: LogAnalyzer):
    """✅ НОВОЕ: Экспорт сделок в CSV"""
    print("\n📋 Экспорт сделок в CSV")
    date = input("Дата (YYYY-MM-DD, Enter для последней сессии): ").strip()

    if date:
        log_files = analyzer.find_log_files(date=date)
        output_path = analyzer.logs_dir / f"trades_{date}.csv"
    else:
        log_files = analyzer.find_log_files()
        output_path = None

    if not log_files:
        print("❌ Лог файлы не найдены")
        return

    print(f"Обработка {len(log_files)} файлов...")
    stats, parsed_logs = analyzer.analyze_session(log_files)

    csv_path = analyzer.export_trades_to_csv(parsed_logs, output_path)
    print(f"\n✅ Сделки экспортированы в CSV: {csv_path}")


def archive_logs_menu():
    """✅ НОВОЕ: Меню архивации логов"""
    print("\n🗄️  Архивация логов")
    print("Выполняется автоматическая архивация логов...")

    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from archive_logs import archive_old_logs

    archive_old_logs()
    print("\n✅ Архивация завершена")


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(description="Анализатор логов торгового бота")
    parser.add_argument("--quick", action="store_true", help="Быстрый анализ")
    parser.add_argument("--date", type=str, help="Анализ по дате (YYYY-MM-DD)")
    parser.add_argument(
        "--compare", nargs=2, metavar=("DATE1", "DATE2"), help="Сравнение сессий"
    )
    parser.add_argument("--output", type=str, help="Путь для сохранения отчета")
    parser.add_argument("--investor", action="store_true", help="Отчет для инвесторов")
    parser.add_argument(
        "--developer", action="store_true", help="Отчет для разработчиков"
    )
    parser.add_argument(
        "--export-json", action="store_true", help="Экспорт сделок в JSON"
    )
    parser.add_argument(
        "--export-csv", action="store_true", help="Экспорт сделок в CSV"
    )
    parser.add_argument("--archive", action="store_true", help="Архивация логов")

    args = parser.parse_args()

    analyzer = LogAnalyzer()

    if args.quick:
        quick_analysis(analyzer)
    elif args.date:
        log_files = analyzer.find_log_files(date=args.date)
        stats, parsed_logs = analyzer.analyze_session(log_files)
        print(f"📊 Анализ за {args.date}:")
        print(f"Прибыль: ${stats.profit:.2f}")

        if args.investor:
            report_id = (
                stats.start_time.strftime("%Y-%m-%d_%H-%M-%S")
                if stats.start_time
                else datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            )
            output_dir = Path("logs/reports/charts")
            analyzer.generate_charts(
                stats, parsed_logs, output_dir, report_id=report_id
            )
            report_path = Path("logs/reports") / f"investor_report_{report_id}.html"
            analyzer.generate_investor_report(
                stats,
                parsed_logs,
                report_path,
                report_id=report_id,
                charts_dir=output_dir,
            )

        if args.developer:
            report_id = (
                stats.start_time.strftime("%Y-%m-%d_%H-%M-%S")
                if stats.start_time
                else datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            )
            output_dir = Path("logs/reports/charts")
            analyzer.generate_charts(
                stats, parsed_logs, output_dir, report_id=report_id
            )
            report_path = Path("logs/reports") / f"developer_report_{report_id}.html"
            analyzer.generate_developer_report(
                stats,
                parsed_logs,
                report_path,
                report_id=report_id,
                charts_dir=output_dir,
            )

        if args.export_json:
            output_path = analyzer.logs_dir / f"trades_{args.date}.json"
            analyzer.export_trades_to_json(parsed_logs, output_path)

        if args.export_csv:
            output_path = analyzer.logs_dir / f"trades_{args.date}.csv"
            analyzer.export_trades_to_csv(parsed_logs, output_path)
    elif args.compare:
        files1 = analyzer.find_log_files(date=args.compare[0])
        files2 = analyzer.find_log_files(date=args.compare[1])
        stats1, _ = analyzer.analyze_session(files1)
        stats2, _ = analyzer.analyze_session(files2)
        comparison = analyzer.compare_sessions(stats1, stats2)
        print(f"Сравнение: {comparison}")
    elif args.archive:
        archive_logs_menu()
    else:
        # Интерактивное меню
        interactive_menu()


if __name__ == "__main__":
    main()
