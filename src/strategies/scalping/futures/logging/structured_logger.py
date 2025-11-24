"""
StructuredLogger - Структурированное логирование.

Сохраняет логи в структурированном формате (JSON) для последующего анализа.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger


class StructuredLogger:
    """
    Структурированный логгер.

    Сохраняет логи в JSON формате для анализа.
    """

    def __init__(self, log_dir: str = "logs/futures/structured"):
        """
        Инициализация StructuredLogger.

        Args:
            log_dir: Директория для структурированных логов
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"✅ StructuredLogger инициализирован (log_dir={log_dir})")

    def log_trade(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
        pnl: float,
        commission: float,
        duration_sec: float,
        reason: str,
        regime: Optional[str] = None,
    ) -> None:
        """
        Логировать сделку.

        Args:
            symbol: Торговый символ
            side: Направление (long/short)
            entry_price: Цена входа
            exit_price: Цена выхода
            size: Размер позиции
            pnl: PnL
            commission: Комиссия
            duration_sec: Длительность в секундах
            reason: Причина закрытия
            regime: Режим рынка
        """
        try:
            # Формируем структурированную запись
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "trade",
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "size": size,
                "pnl": pnl,
                "commission": commission,
                "net_pnl": pnl - commission,
                "duration_sec": duration_sec,
                "duration_min": duration_sec / 60.0,
                "reason": reason,
                "regime": regime,
            }

            # Сохраняем в файл
            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"trades_{date_str}.json"

            # Читаем существующие записи
            trades = []
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        trades = json.load(f)
                except:
                    trades = []

            # Добавляем новую запись
            trades.append(log_entry)

            # Сохраняем обратно
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(trades, f, indent=2, ensure_ascii=False)

            logger.debug(f"✅ StructuredLogger: Сделка {symbol} сохранена в {filepath}")

        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования сделки для {symbol}: {e}",
                exc_info=True,
            )

    def log_signal(
        self,
        symbol: str,
        side: str,
        price: float,
        strength: float,
        regime: Optional[str] = None,
        filters_passed: Optional[list] = None,
    ) -> None:
        """
        Логировать сигнал.

        Args:
            symbol: Торговый символ
            side: Направление (buy/sell)
            price: Цена
            strength: Сила сигнала
            regime: Режим рынка
            filters_passed: Список пройденных фильтров
        """
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "signal",
                "symbol": symbol,
                "side": side,
                "price": price,
                "strength": strength,
                "regime": regime,
                "filters_passed": filters_passed or [],
            }

            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"signals_{date_str}.json"

            signals = []
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        signals = json.load(f)
                except:
                    signals = []

            signals.append(log_entry)

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(signals, f, indent=2, ensure_ascii=False)

            logger.debug(f"✅ StructuredLogger: Сигнал {symbol} сохранен в {filepath}")

        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования сигнала для {symbol}: {e}",
                exc_info=True,
            )
