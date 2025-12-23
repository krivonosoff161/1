"""
🔍 DEBUG LOGGER для полного трейсирования торговли.

Централизованный модуль логирования для отслеживания:
- Каждого тика торговли
- Открытия/закрытия позиций
- Проверок условий (TP/SL/TSL/timeout/min_holding)
- Сигналов и фильтров
- Параметров конфигурации

Использование:
    from src.strategies.modules.debug_logger import DebugLogger
    
    debug_logger = DebugLogger(enabled=True, csv_export=True)
    debug_logger.log_tick(symbol="BTC-USDT", regime="ranging", ...)
"""

import csv
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger


class DebugLogger:
    """
    Детальное логирование с поддержкой CSV экспорта.

    Особенности:
    - Структурированные логи с префиксами (🔄 🔍 ❌ ✨ etc.)
    - CSV экспорт для анализа в Excel
    - Настройка уровня детализации
    - Временные метки для синхронизации
    """

    # Префиксы для разных типов событий
    PREFIXES = {
        "tick": "🔄",
        "config": "⚙️",
        "tsl_create": "✨",
        "tsl_check": "🔍",
        "close": "❌",
        "open": "📤",
        "signal": "📊",
        "filter": "🔥",
        "position": "📍",
        "tp_check": "💰",
        "warning": "⚠️",
        "error": "🚨",
    }

    def __init__(
        self,
        enabled: bool = True,
        csv_export: bool = True,
        csv_dir: str = "logs/futures/debug",  # ✅ ИЗМЕНЕНО: logs/futures/debug вместо logs/debug
        verbose: bool = True,
    ):
        """
        Инициализация Debug Logger.

        Args:
            enabled: Включить/отключить логирование
            csv_export: Экспортировать логи в CSV
            csv_dir: Директория для CSV файлов (по умолчанию logs/futures/debug)
            verbose: Уровень детализации (True = DEBUG, False = WARNING)
        """
        self.enabled = enabled
        self.csv_export = csv_export
        self.verbose = verbose
        self.csv_dir = Path(csv_dir)
        self.csv_file = None
        self.csv_writer = None
        self.session_start = datetime.now()

        if not self.enabled:
            return

        # ✅ ИСПРАВЛЕНО: Используем объединенный CSV файл (all_data_YYYY-MM-DD.csv)
        today = self.session_start.strftime("%Y-%m-%d")
        if self.csv_export:
            unified_csv_path = Path(f"logs/all_data_{today}.csv")
            unified_csv_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Открываем объединенный CSV файл в режиме append
            file_exists = unified_csv_path.exists()
            self.csv_file = open(
                unified_csv_path, "a" if file_exists else "w", newline="", encoding="utf-8"
            )  # noqa: SIM115
            
            # Универсальные поля для объединенного CSV
            fieldnames = [
                "record_type",  # debug, trades, positions_open, orders, signals
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
                "win_rate",
                "regime",
                "order_id",
                "order_type",
                "price",
                "strength",
                "filters_passed",
                "executed",
                "status",
                "fill_price",
                "fill_size",
                "execution_time_ms",
                "slippage",
                "event_type",  # Для debug логов
                "data",  # Для debug логов
            ]
            
            self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=fieldnames)
            
            if not file_exists:
                self.csv_writer.writeheader()
                logger.info(f"✅ DebugLogger: Created unified CSV: {unified_csv_path}")
            else:
                logger.debug(f"✅ DebugLogger: Using existing unified CSV: {unified_csv_path}")

        logger.info(f"✅ DebugLogger инициализирован: CSV в объединенном файле logs/all_data_{today}.csv")

    def __del__(self):
        """Закрытие CSV файла при удалении объекта."""
        if self.csv_file:
            self.csv_file.close()

    def _log(
        self,
        event_type: str,
        symbol: str = "",
        data: Optional[Dict[str, Any]] = None,
        level: str = "debug",
    ) -> None:
        """
        Базовый метод логирования.

        Args:
            event_type: Тип события (tick, config, tsl_check, etc.)
            symbol: Торговый символ
            data: Словарь с данными события
            level: Уровень логирования (debug, info, warning, error)
        """
        if not self.enabled:
            return

        prefix = self.PREFIXES.get(event_type, "📝")
        timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%H:%M:%S.%f")[:-3]

        # Формируем сообщение
        data_str = ""
        if data:
            parts = []
            for key, value in data.items():
                if isinstance(value, float):
                    parts.append(f"{key}={value:.4f}")
                elif isinstance(value, bool):
                    parts.append(f"{key}={value}")
                else:
                    parts.append(f"{key}={value}")
            data_str = " | ".join(parts)

        message = f"{prefix} {event_type.upper()}: {symbol} {data_str}".strip()

        # Логируем
        if level == "debug" and self.verbose:
            logger.debug(message)
        elif level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)

        # ✅ ИСПРАВЛЕНО: Экспортируем в объединенный CSV с record_type
        if self.csv_export and self.csv_writer:
            self.csv_writer.writerow(
                {
                    "record_type": "debug",
                    "timestamp": timestamp.isoformat(),  # Полная ISO дата для совместимости
                    "symbol": symbol,
                    "side": "",
                    "entry_price": "",
                    "exit_price": "",
                    "size": "",
                    "gross_pnl": "",
                    "commission": "",
                    "net_pnl": "",
                    "duration_sec": "",
                    "reason": "",
                    "win_rate": "",
                    "regime": "",
                    "order_id": "",
                    "order_type": "",
                    "price": "",
                    "strength": "",
                    "filters_passed": "",
                    "executed": "",
                    "status": "",
                    "fill_price": "",
                    "fill_size": "",
                    "execution_time_ms": "",
                    "slippage": "",
                    "event_type": event_type,
                    "data": data_str,
                }
            )
            self.csv_file.flush()

    # ============================================================================
    # ПУБЛИЧНЫЕ МЕТОДЫ ДЛЯ ЛОГИРОВАНИЯ
    # ============================================================================

    def log_tick(
        self,
        symbol: str,
        regime: str,
        price: float,
        minutes_running: float = 0.0,
    ) -> None:
        """Логирование тика (начало обработки символа)."""
        self._log(
            "tick",
            symbol,
            {
                "regime": regime,
                "price": price,
                "minutes": minutes_running,
            },
            level="debug" if self.verbose else "info",
        )

    def log_config_loaded(
        self,
        symbol: str,
        regime: str,
        params: Dict[str, Any],
    ) -> None:
        """Логирование загруженной конфигурации."""
        relevant_params = {
            "min_holding": params.get("min_holding_minutes"),
            "timeout": params.get("timeout_minutes"),
            "loss_cut": params.get("loss_cut_percent"),
            "timeout_loss": params.get("timeout_loss_percent"),
            "tp_atr_mult": params.get("tp_atr_multiplier"),
            "initial_trail": params.get("initial_trail"),
        }
        self._log(
            "config",
            symbol,
            {"regime": regime, **relevant_params},
            level="info",
        )

    def log_tsl_created(
        self,
        symbol: str,
        regime: str,
        entry_price: float,
        side: str,
        min_holding: Optional[float],
        timeout: Optional[float],
    ) -> None:
        """Логирование создания TSL."""
        self._log(
            "tsl_create",
            symbol,
            {
                "regime": regime,
                "entry": entry_price,
                "side": side,
                "min_hold": min_holding,
                "timeout": timeout,
            },
            level="info",
        )

    def log_tsl_check(
        self,
        symbol: str,
        minutes_in_position: float,
        profit_pct: float,
        current_price: float,
        stop_loss: float,
        will_close: bool,
    ) -> None:
        """Логирование проверки TSL."""
        self._log(
            "tsl_check",
            symbol,
            {
                "minutes": minutes_in_position,
                "profit": profit_pct,
                "price": current_price,
                "sl": stop_loss,
                "close": will_close,
            },
            level="debug" if not will_close else "warning",
        )

    def log_tsl_min_holding_block(
        self,
        symbol: str,
        minutes_in_position: float,
        min_holding: float,
        profit_pct: float,
    ) -> None:
        """Логирование блокировки закрытия по min_holding."""
        self._log(
            "tsl_check",
            symbol,
            {
                "check": "min_holding_BLOCKED",
                "minutes": minutes_in_position,
                "min_hold": min_holding,
                "profit": profit_pct,
            },
            level="debug",
        )

    def log_tsl_loss_cut_check(
        self,
        symbol: str,
        profit_pct: float,
        loss_cut_from_price: float,
        will_close: bool,
    ) -> None:
        """Логирование проверки loss_cut."""
        self._log(
            "tsl_check",
            symbol,
            {
                "check": "loss_cut",
                "profit": profit_pct,
                "loss_cut": loss_cut_from_price,
                "close": will_close,
            },
            level="warning" if will_close else "debug",
        )

    def log_tsl_timeout_check(
        self,
        symbol: str,
        minutes_in_position: float,
        timeout_minutes: Optional[float],
        profit_pct: float,
        will_close: bool,
    ) -> None:
        """Логирование проверки timeout."""
        self._log(
            "tsl_check",
            symbol,
            {
                "check": "timeout",
                "minutes": minutes_in_position,
                "timeout": timeout_minutes,
                "profit": profit_pct,
                "close": will_close,
            },
            level="warning" if will_close else "debug",
        )

    def log_position_open(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        regime: str,
    ) -> None:
        """Логирование открытия позиции."""
        self._log(
            "open",
            symbol,
            {
                "side": side,
                "price": entry_price,
                "size": size,
                "regime": regime,
            },
            level="info",
        )

    def log_position_close(
        self,
        symbol: str,
        exit_price: float,
        pnl_usd: float,
        pnl_pct: float,
        time_in_position_minutes: float,
        reason: str,
    ) -> None:
        """Логирование закрытия позиции."""
        self._log(
            "close",
            symbol,
            {
                "exit": exit_price,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "time_min": time_in_position_minutes,
                "reason": reason,
            },
            level="info",
        )

    def log_signal_generated(
        self,
        symbol: str,
        direction: str,
        strength: float,
        regime: str,
    ) -> None:
        """Логирование сгенерированного сигнала."""
        self._log(
            "signal",
            symbol,
            {
                "direction": direction,
                "strength": strength,
                "regime": regime,
            },
            level="info",
        )

    def log_filter_result(
        self,
        symbol: str,
        filter_name: str,
        passed: bool,
        reason: str = "",
    ) -> None:
        """Логирование результата фильтра."""
        self._log(
            "filter",
            symbol,
            {
                "filter": filter_name,
                "passed": passed,
                "reason": reason,
            },
            level="debug",
        )

    def log_position_manager_action(
        self,
        symbol: str,
        action: str,
        result: bool,
        reason: str = "",
    ) -> None:
        """Логирование действия Position Manager."""
        self._log(
            "position",
            symbol,
            {
                "action": action,
                "result": result,
                "reason": reason,
            },
            level="info" if result else "debug",
        )

    def log_tp_check(
        self,
        symbol: str,
        current_price: float,
        tp_price: float,
        pnl_pct: float,
        will_close: bool,
    ) -> None:
        """Логирование проверки Take Profit."""
        self._log(
            "tp_check",
            symbol,
            {
                "price": current_price,
                "tp": tp_price,
                "pnl": pnl_pct,
                "close": will_close,
            },
            level="warning" if will_close else "debug",
        )

    def log_warning(self, symbol: str, message: str) -> None:
        """Логирование предупреждения."""
        self._log(
            "warning",
            symbol,
            {"msg": message},
            level="warning",
        )

    def log_error(self, symbol: str, message: str) -> None:
        """Логирование ошибки."""
        self._log(
            "error",
            symbol,
            {"msg": message},
            level="error",
        )
