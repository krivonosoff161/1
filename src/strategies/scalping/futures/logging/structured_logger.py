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
        🔴 BUG #34 FIX (11.01.2026): Changed from JSON array to JSONL (append-only) format

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

            # 🔴 BUG #34 FIX: Use JSONL (append-only) format instead of reading entire file
            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"trades_{date_str}.jsonl"

            # Append single JSON line instead of rewriting entire file
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

            logger.debug(f"✅ StructuredLogger: Сделка {symbol} сохранена в {filepath}")

        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования сделки для {symbol}: {e}",
                exc_info=True,
            )

    def log_exit_diagnosis(
        self,
        symbol: str,
        cause: str,
        rule: str,
        pnl_pct: Optional[float],
        tsl_state: Optional[Dict[str, Any]],
        sl_tp_targets: Optional[Dict[str, Any]],
    ) -> None:
        """Логировать диагностику закрытия позиции."""
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "position_exit_diagnosis",
                "symbol": symbol,
                "cause": cause,
                "rule": rule,
                "pnl_pct": pnl_pct,
                "tsl_state": tsl_state,
                "sl_tp_targets": sl_tp_targets,
            }
            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"position_exit_diagnosis_{date_str}.jsonl"
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            logger.debug(
                f"✅ StructuredLogger: Exit diagnosis {symbol} сохранен в {filepath}"
            )
        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования exit diagnosis для {symbol}: {e}",
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
        🔴 BUG #34 FIX: Using JSONL (append-only) format

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
            filepath = self.log_dir / f"signals_{date_str}.jsonl"

            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

            logger.debug(f"✅ StructuredLogger: Сигнал {symbol} сохранен в {filepath}")

        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования сигнала для {symbol}: {e}",
                exc_info=True,
            )

    def log_filter_reject(
        self,
        symbol: str,
        side: str,
        price: Optional[float],
        strength: float,
        regime: Optional[str],
        reason: str,
        filters_passed: Optional[list] = None,
    ) -> None:
        """Log a structured record for rejected signals (filters or thresholds)."""
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "signal_rejected",
                "symbol": symbol,
                "side": side,
                "price": price,
                "strength": strength,
                "regime": regime,
                "reason": reason,
                "filters_passed": filters_passed or [],
            }

            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"signals_rejected_{date_str}.jsonl"

            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

            logger.debug(
                f"¢?: StructuredLogger: Rejected signal {symbol} saved to {filepath}"
            )
        except Exception as e:
            logger.error(
                f"¢?? StructuredLogger: Failed to log rejected signal for {symbol}: {e}",
                exc_info=True,
            )

    def log_candle_init(
        self,
        symbol: str,
        timeframe: str,
        candles_count: int,
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        """
        Логировать инициализацию буфера свечей.
        🔴 BUG #34 FIX: Using JSONL (append-only)

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, 1D)
            candles_count: Количество загруженных свечей
            status: Статус (success, error)
            error: Сообщение об ошибке (если есть)
        """
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "candle_init",
                "symbol": symbol,
                "timeframe": timeframe,
                "candles_count": candles_count,
                "status": status,
                "error": error,
            }

            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"candles_init_{date_str}.jsonl"

            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

            logger.debug(
                f"✅ StructuredLogger: Инициализация свечей {symbol} {timeframe} сохранена"
            )

        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования инициализации свечей: {e}",
                exc_info=True,
            )

    def log_candle_new(
        self,
        symbol: str,
        timeframe: str,
        timestamp: int,
        price: float,
        open_price: float,  # ✅ ИСПРАВЛЕНО: переименовано из 'open' чтобы избежать конфликта с встроенной функцией
        high: float,
        low: float,
        close: float,
        volume: Optional[float] = None,
    ) -> None:
        """
        Логировать создание новой свечи.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм (1m, 5m, 1H, 1D)
            timestamp: Timestamp свечи
            price: Цена (обычно равна close)
            open_price: Цена открытия
            high: Максимальная цена
            low: Минимальная цена
            close: Цена закрытия
        """
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "candle_new",
                "symbol": symbol,
                "timeframe": timeframe,
                "candle_timestamp": timestamp,
                "price": price,
                "open": open_price,  # ✅ ИСПРАВЛЕНО: используем open_price
                "high": high,
                "low": low,
                "close": close,
            }
            if volume is not None:
                log_entry["volume"] = volume

            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"candles_new_{date_str}.json"

            entries = []
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                except:
                    entries = []

            entries.append(log_entry)

            # Ограничиваем размер файла (последние 1000 записей)
            if len(entries) > 1000:
                entries = entries[-1000:]

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)

            logger.debug(
                f"✅ StructuredLogger: Новая свеча {symbol} {timeframe} сохранена"
            )

        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования новой свечи: {e}",
                exc_info=True,
            )

    def log_candle_usage(
        self,
        filter_name: str,
        symbol: str,
        timeframe: str,
        source: str,
        candles_count: int,
        fallback_to_api: bool = False,
    ) -> None:
        """
        Логировать использование свечей фильтрами.

        Args:
            filter_name: Название фильтра (MTF, VolumeProfile, PivotPoints, Correlation)
            symbol: Торговый символ
            timeframe: Таймфрейм
            source: Источник (dataregistry, api)
            candles_count: Количество полученных свечей
            fallback_to_api: Был ли использован fallback к API
        """
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "candle_usage",
                "filter_name": filter_name,
                "symbol": symbol,
                "timeframe": timeframe,
                "source": source,
                "candles_count": candles_count,
                "fallback_to_api": fallback_to_api,
            }

            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"candles_usage_{date_str}.json"

            entries = []
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                except:
                    entries = []

            entries.append(log_entry)

            # Ограничиваем размер файла (последние 500 записей)
            if len(entries) > 500:
                entries = entries[-500:]

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)

            logger.debug(
                f"✅ StructuredLogger: Использование свечей {filter_name} {symbol} {timeframe} сохранено"
            )

        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования использования свечей: {e}",
                exc_info=True,
            )

    def log_candle_stats(
        self,
        symbol: str,
        timeframe: str,
        candles_count: int,
        buffer_size: int,
        last_update: Optional[str] = None,
    ) -> None:
        """
        Логировать статистику буфера свечей.

        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм
            candles_count: Текущее количество свечей
            buffer_size: Максимальный размер буфера
            last_update: Время последнего обновления
        """
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "type": "candle_stats",
                "symbol": symbol,
                "timeframe": timeframe,
                "candles_count": candles_count,
                "buffer_size": buffer_size,
                "usage_percent": (candles_count / buffer_size * 100)
                if buffer_size > 0
                else 0,
                "last_update": last_update or datetime.now().isoformat(),
            }

            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = self.log_dir / f"candles_stats_{date_str}.json"

            entries = []
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                except:
                    entries = []

            entries.append(log_entry)

            # Ограничиваем размер файла (последние 200 записей)
            if len(entries) > 200:
                entries = entries[-200:]

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)

            logger.debug(
                f"✅ StructuredLogger: Статистика свечей {symbol} {timeframe} сохранена"
            )

        except Exception as e:
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования статистики свечей: {e}",
                exc_info=True,
            )
            logger.error(
                f"❌ StructuredLogger: Ошибка логирования сигнала для {symbol}: {e}",
                exc_info=True,
            )
