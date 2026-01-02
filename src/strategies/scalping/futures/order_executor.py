"""
Futures Order Executor для скальпинг стратегии.

Основные функции:
- Исполнение торговых сигналов в Futures
- Интеграция с Slippage Guard для контроля проскальзывания
- Управление ордерами (рыночные, лимитные, OCO)
- Обработка ошибок и повторные попытки
"""

import asyncio
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig, ScalpingConfig
from src.strategies.modules.slippage_guard import SlippageGuard


class FuturesOrderExecutor:
    """
    Исполнитель ордеров для Futures торговли

    Функции:
    - Исполнение торговых сигналов
    - Управление различными типами ордеров
    - Интеграция с Slippage Guard
    - Обработка ошибок и повторные попытки
    """

    def __init__(
        self, config: BotConfig, client: OKXFuturesClient, slippage_guard: SlippageGuard
    ):
        """
        Инициализация Futures Order Executor

        Args:
            config: Конфигурация бота
            client: Futures клиент
            slippage_guard: Защита от проскальзывания
        """
        self.config = config
        self.scalping_config = config.scalping
        self.client = client
        self.slippage_guard = slippage_guard
        self.performance_tracker = None  # Будет установлен из orchestrator
        self.data_registry = None  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): DataRegistry для получения волатильности
        self.signal_generator = None  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): SignalGenerator для получения волатильности

        # Состояние
        self.is_initialized = False
        self.active_orders = {}
        self.order_history = []
        self.execution_stats = {
            "total_orders": 0,
            "successful_orders": 0,
            "failed_orders": 0,
            "cancelled_orders": 0,
            # ✅ Метрики исполнения
            "market_orders": 0,
            "limit_orders_maker": 0,
            "limit_orders_other": 0,
            "total_slippage_bps": 0.0,
            "slippage_samples": 0,
        }

        logger.info("FuturesOrderExecutor инициализирован")

    async def initialize(self):
        """Инициализация исполнителя ордеров"""
        try:
            # Проверка подключения к клиенту
            balance = await self.client.get_balance()
            logger.info(
                f"✅ Подключение к Futures клиенту установлено. Баланс: {balance:.2f} USDT"
            )

            self.is_initialized = True
            logger.info("✅ FuturesOrderExecutor инициализирован")

        except Exception as e:
            logger.error(f"Ошибка инициализации FuturesOrderExecutor: {e}")
            raise

    def set_performance_tracker(self, performance_tracker):
        """Установить PerformanceTracker для логирования"""
        self.performance_tracker = performance_tracker
        logger.debug("✅ FuturesOrderExecutor: PerformanceTracker установлен")

    def set_data_registry(self, data_registry):
        """✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): Установить DataRegistry для получения волатильности"""
        self.data_registry = data_registry
        logger.debug("✅ FuturesOrderExecutor: DataRegistry установлен")

    def set_signal_generator(self, signal_generator):
        """✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): Установить SignalGenerator для получения волатильности"""
        self.signal_generator = signal_generator
        logger.debug("✅ FuturesOrderExecutor: SignalGenerator установлен")

    async def execute_signal(
        self, signal: Dict[str, Any], position_size: float
    ) -> Dict[str, Any]:
        """
        Исполнение торгового сигнала

        Args:
            signal: Торговый сигнал
            position_size: Размер позиции

        Returns:
            Результат исполнения
        """
        if not self.is_initialized:
            return {"success": False, "error": "Executor не инициализирован"}

        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            signal_type = signal.get(
                "type", "limit"
            )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий

            logger.info(
                f"🎯 Исполнение сигнала: {symbol} {side} размер={position_size:.6f}"
            )

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Логируем информацию о сигнале
            logger.debug(
                f"🔍 [EXECUTE_SIGNAL] {symbol} {side}: "
                f"size={position_size:.6f}, signal_type={signal.get('type', 'limit')}, "
                f"regime={signal.get('regime', 'N/A')}, strength={signal.get('strength', 0):.2f}"
            )

            # Валидация сигнала через Slippage Guard
            (
                is_valid,
                reason,
            ) = await self.slippage_guard.validate_order_before_placement(
                symbol=symbol,
                side=side,
                order_type="market",
                price=None,
                size=position_size,
                client=self.client,
            )

            if not is_valid:
                # ✅ FIX: Улучшенный logging для gap/spread блокировки
                if "спред" in reason.lower() or "spread" in reason.lower():
                    logger.warning(f"GAP_BLOCK {symbol}: {reason}")
                elif (
                    "проскальзывание" in reason.lower() or "slippage" in reason.lower()
                ):
                    logger.warning(f"SLIPPAGE_BLOCK {symbol}: {reason}")
                else:
                    logger.warning(f"VALIDATION_BLOCK {symbol}: {reason}")
                return {"success": False, "error": f"Валидация не пройдена: {reason}"}

            # Исполнение ордера
            result = await self._execute_order(signal, position_size)

            # Обновление статистики
            self._update_execution_stats(result)

            return result

        except Exception as e:
            logger.error(f"Ошибка исполнения сигнала: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_order(
        self, signal: Dict[str, Any], position_size: float
    ) -> Dict[str, Any]:
        """Исполнение ордера"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            signal_type = signal.get(
                "type", "limit"
            )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий

            # Определение типа ордера
            order_type = self._determine_order_type(signal)

            # Расчет цены для лимитных ордеров
            price = None
            if order_type == "limit":
                # ✅ НОВОЕ: Получаем режим из сигнала для адаптивного offset
                regime = signal.get("regime", None)
                # ✅ ОПТИМИЗАЦИЯ: Передаем signal для использования signal["price"] если актуальна
                price = await self._calculate_limit_price(
                    symbol, side, regime=regime, signal=signal
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если не удалось рассчитать цену - используем рыночный ордер
                if price is None or price <= 0:
                    logger.warning(
                        f"⚠️ Не удалось рассчитать цену для лимитного ордера {symbol}, "
                        f"используем рыночный ордер как fallback"
                    )
                    order_type = "market"
                    price = None

            # ✅ НОВОЕ (03.01.2026): Логирование типа ордера и источника
            logger.info(
                f"📊 [PARAMS] {symbol}: order_type={order_type} | "
                f"Источник: _determine_order_type() (signal.type={signal.get('type', 'N/A')})"
            )
            
            # Размещение ордера
            if order_type == "market":
                result = await self._place_market_order(symbol, side, position_size)
            elif order_type == "limit":
                # ✅ ИСПРАВЛЕНО: Передаем regime в _place_limit_order для применения режимных параметров
                regime = signal.get("regime", None)
                result = await self._place_limit_order(
                    symbol, side, position_size, price, regime=regime
                )
            elif order_type == "oco":
                result = await self._place_oco_order(signal, position_size)
            else:
                raise ValueError(f"Неподдерживаемый тип ордера: {order_type}")

            # Сохранение ордера
            if result.get("success"):
                order_id = result.get("order_id")
                self.active_orders[order_id] = {
                    "symbol": symbol,
                    "side": side,
                    "size": position_size,
                    "type": order_type,  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: Limit ордера для экономии комиссий
                    "timestamp": datetime.now(),
                    "signal": signal,
                }

                # ✅ НОВОЕ: Логирование размещения ордера в CSV
                if self.performance_tracker:
                    try:
                        self.performance_tracker.record_order(
                            symbol=symbol,
                            side=side,
                            order_type=order_type,
                            order_id=order_id or "",
                            size=position_size,
                            price=price,
                            status="placed",
                        )
                        logger.debug(
                            f"✅ OrderExecutor: Размещение ордера {order_id} записано в CSV"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ OrderExecutor: Ошибка записи размещения ордера в CSV: {e}"
                        )

            return result

        except Exception as e:
            logger.error(f"Ошибка исполнения ордера: {e}")
            return {"success": False, "error": str(e)}

    def _determine_order_type(self, signal: Dict[str, Any]) -> str:
        """Определение типа ордера на основе сигнала"""
        # ✅ ИЗМЕНЕНО (03.01.2026): Переключение на market ордера для мгновенного исполнения
        # Market ордера дают актуальный вход без потери времени на мониторинг limit ордеров
        # Комиссия выше (0.05% вместо 0.02%), но не критична при профите $4-7
        signal_type = signal.get(
            "type", "market"
        )  # ✅ ИЗМЕНЕНО: "market" вместо "limit" для мгновенного исполнения

        # Если signal_type это тип ордера (market, limit, oco) - используем его
        if signal_type in ["market", "limit", "oco"]:
            return signal_type

        # ✅ ИЗМЕНЕНО: Используем market по умолчанию для мгновенного исполнения
        # Это решает проблему потери времени и несоответствия анализа и входа
        return "market"  # ✅ ИЗМЕНЕНО: "market" вместо "limit"

    async def _calculate_limit_price(
        self,
        symbol: str,
        side: str,
        regime: Optional[str] = None,
        signal: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        ✅ УЛУЧШЕННЫЙ: Расчет цены для лимитного ордера с учетом режима рынка
        Использует настраиваемый offset из конфига для адаптации под разные режимы
        """
        try:
            # ✅ НОВОЕ: Получаем конфигурацию лимитных ордеров
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем как dict и как атрибут
            order_executor_config = None
            if isinstance(self.scalping_config, dict):
                order_executor_config = self.scalping_config.get("order_executor")
            else:
                order_executor_config = getattr(
                    self.scalping_config, "order_executor", None
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если None, пробуем получить через model_dump
                if order_executor_config is None and hasattr(
                    self.scalping_config, "model_dump"
                ):
                    try:
                        scalping_dict = self.scalping_config.model_dump()
                        order_executor_config = scalping_dict.get("order_executor")
                    except Exception:
                        pass
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если None, пробуем получить через dict()
                if order_executor_config is None and hasattr(
                    self.scalping_config, "dict"
                ):
                    try:
                        scalping_dict = self.scalping_config.dict()
                        order_executor_config = scalping_dict.get("order_executor")
                    except Exception:
                        pass
                # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Если это Pydantic модель, пробуем model_dump
                if order_executor_config is None and hasattr(
                    self.scalping_config, "model_dump"
                ):
                    try:
                        scalping_dict = self.scalping_config.model_dump()
                        order_executor_config = scalping_dict.get("order_executor")
                    except Exception:
                        pass
                # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Если это Pydantic v1, пробуем dict()
                if order_executor_config is None and hasattr(
                    self.scalping_config, "dict"
                ):
                    try:
                        scalping_dict = self.scalping_config.dict()
                        order_executor_config = scalping_dict.get("order_executor")
                    except Exception:
                        pass

            # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: Проверяем что order_executor_config существует
            if order_executor_config is None:
                logger.warning(
                    f"⚠️ order_executor_config не найден в scalping_config для {symbol}. "
                    f"Доступные атрибуты: {[attr for attr in dir(self.scalping_config) if not attr.startswith('_')]}"
                )
                order_executor_config = {}

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
            if not isinstance(order_executor_config, dict):
                if hasattr(order_executor_config, "dict"):
                    order_executor_config = order_executor_config.dict()
                elif hasattr(order_executor_config, "model_dump"):
                    order_executor_config = order_executor_config.model_dump()
                elif hasattr(order_executor_config, "__dict__"):
                    order_executor_config = dict(order_executor_config.__dict__)
                else:
                    logger.warning(
                        f"⚠️ order_executor_config не может быть преобразован в dict для {symbol}: "
                        f"type={type(order_executor_config)}"
                    )
                    order_executor_config = {}

            # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: Проверяем структуру order_executor_config
            logger.debug(
                f"🔍 order_executor_config для {symbol}: type={type(order_executor_config)}, "
                f"keys={list(order_executor_config.keys()) if isinstance(order_executor_config, dict) else 'N/A'}"
            )
            # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: Проверяем scalping_config напрямую
            if order_executor_config is None or (
                isinstance(order_executor_config, dict) and not order_executor_config
            ):
                logger.warning(
                    f"⚠️ order_executor_config пустой для {symbol}. "
                    f"Проверяем scalping_config напрямую: "
                    f"type={type(self.scalping_config)}, "
                    f"hasattr order_executor={hasattr(self.scalping_config, 'order_executor')}"
                )
                # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Пробуем получить через __dict__
                if hasattr(self.scalping_config, "__dict__"):
                    scalping_dict = self.scalping_config.__dict__
                    logger.debug(
                        f"🔍 scalping_config.__dict__ keys: {list(scalping_dict.keys())}"
                    )
                    if "order_executor" in scalping_dict:
                        order_executor_raw = scalping_dict["order_executor"]
                        logger.info(
                            f"✅ order_executor найден через __dict__ для {symbol}"
                        )
                        # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: Проверяем что находится в order_executor
                        logger.debug(
                            f"🔍 order_executor_raw для {symbol}: type={type(order_executor_raw)}, "
                            f"is_dict={isinstance(order_executor_raw, dict)}, "
                            f"keys={list(order_executor_raw.keys()) if isinstance(order_executor_raw, dict) else 'N/A'}, "
                            f"value={order_executor_raw if isinstance(order_executor_raw, dict) and len(str(order_executor_raw)) < 200 else 'too large'}"
                        )
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
                        if not isinstance(order_executor_raw, dict):
                            if hasattr(order_executor_raw, "model_dump"):
                                order_executor_config = order_executor_raw.model_dump()
                                logger.debug(
                                    f"✅ order_executor преобразован через model_dump() для {symbol}"
                                )
                            elif hasattr(order_executor_raw, "dict"):
                                order_executor_config = order_executor_raw.dict()
                                logger.debug(
                                    f"✅ order_executor преобразован через dict() для {symbol}"
                                )
                            elif hasattr(order_executor_raw, "__dict__"):
                                order_executor_config = dict(
                                    order_executor_raw.__dict__
                                )
                                logger.debug(
                                    f"✅ order_executor преобразован через __dict__ для {symbol}"
                                )
                            else:
                                logger.warning(
                                    f"⚠️ order_executor не может быть преобразован в dict для {symbol}: "
                                    f"type={type(order_executor_raw)}"
                                )
                        else:
                            order_executor_config = order_executor_raw
                            logger.debug(f"✅ order_executor уже dict для {symbol}")
                        # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: Проверяем содержимое order_executor_config
                        logger.debug(
                            f"🔍 order_executor_config после преобразования для {symbol}: "
                            f"type={type(order_executor_config)}, "
                            f"keys={list(order_executor_config.keys()) if isinstance(order_executor_config, dict) else 'N/A'}"
                        )

            limit_order_config = order_executor_config.get("limit_order", {})
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
            if not isinstance(limit_order_config, dict):
                if hasattr(limit_order_config, "dict"):
                    limit_order_config = limit_order_config.dict()
                elif hasattr(limit_order_config, "model_dump"):
                    limit_order_config = limit_order_config.model_dump()
                elif hasattr(limit_order_config, "__dict__"):
                    limit_order_config = dict(limit_order_config.__dict__)
                else:
                    limit_order_config = {}
            # ✅ ДОПОЛНИТЕЛЬНОЕ ЛОГИРОВАНИЕ: Проверяем наличие by_symbol в конфиге
            logger.debug(
                f"🔍 Проверка конфига для {symbol}: limit_order_config keys={list(limit_order_config.keys()) if isinstance(limit_order_config, dict) else 'N/A'}, "
                f"by_symbol exists={bool(limit_order_config.get('by_symbol'))}, "
                f"by_regime exists={bool(limit_order_config.get('by_regime'))}"
            )
            # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: Проверяем структуру order_executor_config
            if not isinstance(order_executor_config, dict) or not order_executor_config:
                logger.warning(
                    f"⚠️ order_executor_config пустой или не dict для {symbol}: "
                    f"type={type(order_executor_config)}, value={order_executor_config}"
                )
            if not isinstance(limit_order_config, dict) or not limit_order_config:
                logger.warning(
                    f"⚠️ limit_order_config пустой или не dict для {symbol}: "
                    f"type={type(limit_order_config)}, value={limit_order_config}"
                )

            # Получаем offset из конфига (с учетом символа и режима)
            default_offset = limit_order_config.get(
                "limit_offset_percent", 0.0
            )  # По умолчанию 0% (best bid/ask)

            # ✅ НОВОЕ: Приоритет 1 - Per-symbol + Per-regime (если есть)
            offset_percent = (
                None  # Используем None для отслеживания, был ли найден offset
            )
            if symbol and limit_order_config.get("by_symbol"):
                by_symbol_dict = limit_order_config.get("by_symbol", {})
                # ✅ ДОПОЛНИТЕЛЬНОЕ ЛОГИРОВАНИЕ: Проверяем что by_symbol не пустой
                logger.debug(
                    f"🔍 Проверка by_symbol для {symbol}: by_symbol_dict type={type(by_symbol_dict)}, "
                    f"keys={list(by_symbol_dict.keys()) if isinstance(by_symbol_dict, dict) else 'N/A'}"
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
                if not isinstance(by_symbol_dict, dict):
                    if hasattr(by_symbol_dict, "dict"):
                        by_symbol_dict = by_symbol_dict.dict()
                    elif hasattr(by_symbol_dict, "model_dump"):
                        by_symbol_dict = by_symbol_dict.model_dump()
                    elif hasattr(by_symbol_dict, "__dict__"):
                        by_symbol_dict = dict(by_symbol_dict.__dict__)
                    else:
                        by_symbol_dict = {}
                symbol_config = by_symbol_dict.get(symbol, {})
                # ✅ ДОПОЛНИТЕЛЬНОЕ ЛОГИРОВАНИЕ: Проверяем что symbol_config найден
                logger.debug(
                    f"🔍 Проверка symbol_config для {symbol}: symbol_config type={type(symbol_config)}, "
                    f"is_empty={not bool(symbol_config)}, keys={list(symbol_config.keys()) if isinstance(symbol_config, dict) else 'N/A'}"
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
                if not isinstance(symbol_config, dict):
                    if hasattr(symbol_config, "dict"):
                        symbol_config = symbol_config.dict()
                    elif hasattr(symbol_config, "model_dump"):
                        symbol_config = symbol_config.model_dump()
                    elif hasattr(symbol_config, "__dict__"):
                        symbol_config = dict(symbol_config.__dict__)
                    else:
                        symbol_config = {}
                if symbol_config:
                    # Проверяем, есть ли настройки для режима внутри символа
                    if regime and symbol_config.get("by_regime"):
                        by_regime_dict = symbol_config.get("by_regime", {})
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
                        if not isinstance(by_regime_dict, dict):
                            if hasattr(by_regime_dict, "dict"):
                                by_regime_dict = by_regime_dict.dict()
                            elif hasattr(by_regime_dict, "model_dump"):
                                by_regime_dict = by_regime_dict.model_dump()
                            elif hasattr(by_regime_dict, "__dict__"):
                                by_regime_dict = dict(by_regime_dict.__dict__)
                            else:
                                by_regime_dict = {}
                        regime_config = by_regime_dict.get(regime, {})
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
                        if not isinstance(regime_config, dict):
                            if hasattr(regime_config, "dict"):
                                regime_config = regime_config.dict()
                            elif hasattr(regime_config, "model_dump"):
                                regime_config = regime_config.model_dump()
                            elif hasattr(regime_config, "__dict__"):
                                regime_config = dict(regime_config.__dict__)
                            else:
                                regime_config = {}
                        symbol_regime_offset = regime_config.get("limit_offset_percent")
                        if symbol_regime_offset is not None:
                            offset_percent = symbol_regime_offset
                            logger.debug(
                                f"💰 Per-symbol+regime offset для {symbol} ({regime}): {offset_percent}%"
                            )
                        else:
                            # ✅ FALLBACK: Per-symbol offset (режим не найден в per-symbol, используем per-symbol)
                            symbol_offset = symbol_config.get("limit_offset_percent")
                            if symbol_offset is not None:
                                offset_percent = symbol_offset
                                logger.debug(
                                    f"💰 Per-symbol offset для {symbol}: {offset_percent}% "
                                    f"(режим {regime} не найден в per-symbol, используется per-symbol)"
                                )
                    else:
                        # Только per-symbol offset (без режима)
                        symbol_offset = symbol_config.get("limit_offset_percent")
                        if symbol_offset is not None:
                            offset_percent = symbol_offset
                            logger.debug(
                                f"💰 Per-symbol offset для {symbol}: {offset_percent}%"
                            )

            # ✅ Приоритет 2 - Per-regime (если per-symbol не найден)
            if (
                offset_percent is None
                and regime
                and limit_order_config.get("by_regime")
            ):
                by_regime_dict = limit_order_config.get("by_regime", {})
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
                if not isinstance(by_regime_dict, dict):
                    if hasattr(by_regime_dict, "dict"):
                        by_regime_dict = by_regime_dict.dict()
                    elif hasattr(by_regime_dict, "model_dump"):
                        by_regime_dict = by_regime_dict.model_dump()
                    elif hasattr(by_regime_dict, "__dict__"):
                        by_regime_dict = dict(by_regime_dict.__dict__)
                    else:
                        by_regime_dict = {}
                regime_config = by_regime_dict.get(regime, {})
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Преобразуем в dict если это объект
                if not isinstance(regime_config, dict):
                    if hasattr(regime_config, "dict"):
                        regime_config = regime_config.dict()
                    elif hasattr(regime_config, "model_dump"):
                        regime_config = regime_config.model_dump()
                    elif hasattr(regime_config, "__dict__"):
                        regime_config = dict(regime_config.__dict__)
                    else:
                        regime_config = {}
                regime_offset = regime_config.get("limit_offset_percent")
                if regime_offset is not None:
                    offset_percent = regime_offset
                    logger.debug(f"💰 Per-regime offset для {regime}: {offset_percent}%")

                # Проверяем, нужно ли использовать рыночные ордера в этом режиме
                use_market = regime_config.get("use_market_order", False)
                if use_market:
                    logger.debug(
                        f"📊 Режим {regime} требует рыночные ордера, возвращаем 0 для fallback на market"
                    )
                    return 0.0  # Возвращаем 0 для fallback на рыночный ордер

            # ✅ Приоритет 3 - Глобальный fallback (если ничего не найдено)
            if offset_percent is None:
                offset_percent = default_offset
                # ✅ ДОПОЛНИТЕЛЬНОЕ ЛОГИРОВАНИЕ: Подробная информация о том, почему используется fallback
                by_symbol_exists = bool(limit_order_config.get("by_symbol"))
                by_regime_exists = bool(limit_order_config.get("by_regime"))
                logger.info(
                    f"📊 [LIMIT_PRICE] {symbol}: Используется глобальный offset={offset_percent}% "
                    f"(per-symbol+regime и per-regime не найдены, regime={regime or 'N/A'})"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка, что offset_percent не слишком большой
            # Если offset > 1% - это ошибка конфига или чтения
            if offset_percent > 1.0:
                logger.error(
                    f"❌ КРИТИЧЕСКАЯ ОШИБКА: offset_percent={offset_percent}% слишком большой для {symbol}! "
                    f"Используем безопасный fallback 0.05%"
                )
                offset_percent = 0.05  # Безопасный fallback

            # Получаем лимиты цены биржи (включая лучшие цены из стакана)
            price_limits = await self.client.get_price_limits(symbol)

            # ✅ НОВОЕ: Проверка свежести цены (не старше 1 секунды)
            if price_limits:
                price_timestamp = price_limits.get("timestamp", 0)
                if price_timestamp > 0:
                    price_age = time.time() - price_timestamp
                    if price_age > 1.0:  # Цена старше 1 секунды
                        logger.warning(
                            f"⚠️ Цена для {symbol} устарела ({price_age:.2f} сек), "
                            f"обновляем данные..."
                        )
                        # Обновляем цену
                        price_limits = await self.client.get_price_limits(symbol)

            if not price_limits:
                logger.warning(
                    f"⚠️ Не удалось получить лимиты цены для {symbol}, используем fallback"
                )
                # Fallback: используем текущую цену с безопасным offset
                import aiohttp

                inst_id = f"{symbol}-SWAP"
                url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("code") == "0" and data.get("data"):
                                ticker = data["data"][0]
                                current_price = float(ticker.get("last", "0"))
                                if current_price > 0:
                                    # ✅ ИСПРАВЛЕНО: Используем более безопасный offset 0.1% (вместо 0.05%)
                                    # Для обоих случаев (BUY и SELL) используем -0.1% от текущей цены
                                    # Это гарантирует исполнение и не выходит за лимиты биржи
                                    limit_price = (
                                        current_price * 0.999
                                    )  # -0.1% от текущей цены
                                    logger.debug(
                                        f"💰 Лимитная цена (fallback) для {symbol} {side}: {limit_price:.2f}"
                                    )
                                    return limit_price
                return 0.0

            # ✅ ИСПРАВЛЕНО: Используем лучшие цены из стакана для более точного расчета
            best_bid = price_limits.get("best_bid", 0)
            best_ask = price_limits.get("best_ask", 0)
            current_price = price_limits.get("current_price", 0)
            max_buy_price = price_limits.get("max_buy_price", 0)
            min_sell_price = price_limits.get("min_sell_price", 0)

            if current_price <= 0:
                logger.error(f"❌ Неверная текущая цена для {symbol}: {current_price}")
                return 0.0

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для скальпинга ВСЕГДА используем актуальную цену из стакана
            # НЕ используем signal_price как base_price - это может привести к размещению ордеров далеко от рынка
            # Для скальпинга критична скорость и точность цены - используем best_ask/best_bid или current_price
            signal_price = None
            if signal:
                signal_price = signal.get("price", 0.0)
                if signal_price > 0:
                    price_diff_pct = (
                        abs(signal_price - current_price) / current_price * 100
                        if current_price > 0
                        else 100
                    )
                    # ✅ ИСПРАВЛЕНО: Более строгая проверка для скальпинга (0.1% вместо 0.5%)
                    if price_diff_pct < 0.1:  # Разница < 0.1% - сигнал актуален
                        logger.debug(
                            f"💰 signal['price']={signal_price:.2f} актуальна для {symbol} {side} "
                            f"(разница с current_price={current_price:.2f} составляет {price_diff_pct:.3f}%)"
                        )
                        # ✅ НОВОЕ: Используем signal_price только как fallback, если best_ask/best_bid недоступны
                        # Основная логика использует best_ask/best_bid для точности
                        base_price = signal_price
                    else:
                        logger.warning(
                            f"⚠️ signal['price']={signal_price:.2f} устарела для {symbol} {side} "
                            f"(разница с current_price={current_price:.2f} составляет {price_diff_pct:.3f}%), "
                            f"используем current_price"
                        )
                        base_price = current_price
                else:
                    base_price = current_price
            else:
                base_price = current_price

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для скальпинга ПРИОРИТЕТ - best_ask/best_bid, НЕ base_price
            # base_price используется только как fallback если best_ask/best_bid недоступны

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем правильную логику для SELL и BUY
            # ✅ НОВОЕ: Используем настраиваемый offset из конфига
            # ✅ НОВОЕ: Адаптивный offset на основе спреда (если включен)
            # Для BUY: покупаем по цене best ask + offset (для быстрого исполнения в скальпинге)
            # Для SELL: продаем по цене best bid - offset (для быстрого исполнения в скальпинге)

            # ✅ НОВОЕ: Проверяем, включен ли адаптивный offset на основе спреда
            adaptive_spread_offset = limit_order_config.get(
                "adaptive_spread_offset", False
            )

            # ✅ НОВОЕ: Рассчитываем спред для адаптивного offset
            spread = 0.0
            spread_pct = 0.0
            adaptive_offset_pct = None

            if adaptive_spread_offset and best_ask > 0 and best_bid > 0:
                spread = best_ask - best_bid
                if best_ask > 0:
                    spread_pct = (spread / best_ask) * 100.0

                # ✅ НОВОЕ: Адаптивный offset с учетом ширины спреда
                # < 0.001% → offset = 0 (ровно по best_ask/best_bid)
                # 0.001-0.01% → offset = 10% спреда
                # ≥ 0.01% → offset = 20% спреда, макс 0.05%
                if spread_pct > 0 and spread_pct <= 1.0:  # Только если спред <= 1%
                    if spread_pct < 0.001:  # < 0.001% - сверхузкий спред
                        adaptive_offset_pct = 0.0  # Ровно по best_ask/best_bid
                        logger.debug(
                            f"💰 Адаптивный offset для {symbol}: spread={spread:.6f} ({spread_pct:.4f}%) - "
                            f"сверхузкий спред, offset=0 (ровно по best_ask/best_bid)"
                        )
                    elif spread_pct < 0.01:  # 0.001-0.01% - узкий спред
                        adaptive_offset_pct = spread_pct * 0.1  # 10% спреда
                        logger.debug(
                            f"💰 Адаптивный offset для {symbol}: spread={spread:.6f} ({spread_pct:.4f}%) - "
                            f"узкий спред, offset=10% спреда = {adaptive_offset_pct:.4f}%"
                        )
                    else:  # ≥ 0.01% - нормальный спред
                        adaptive_offset_pct = max(
                            spread_pct * 0.2, min(0.05, spread_pct * 2.0)
                        )
                        logger.debug(
                            f"💰 Адаптивный offset для {symbol}: spread={spread:.6f} ({spread_pct:.4f}%) - "
                            f"нормальный спред, offset=20% спреда = {adaptive_offset_pct:.4f}%"
                        )
                else:
                    # Спред слишком большой (>1%) или нулевой - используем offset из конфига
                    logger.debug(
                        f"💰 Спред для {symbol} слишком большой ({spread_pct:.4f}%) или нулевой, "
                        f"используем offset из конфига: {offset_percent:.3f}%"
                    )

            if side.lower() == "buy":
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем актуальность best_ask
                # Увеличиваем порог до 0.5% для более гибкой работы
                use_best_ask = False
                if best_ask > 0 and current_price > 0:
                    ask_price_diff_pct = abs(best_ask - current_price) / current_price
                    # ✅ ИСПРАВЛЕНО: Используем best_ask если разница < 0.5% (было 0.1%)
                    if ask_price_diff_pct < 0.005:
                        use_best_ask = True
                        logger.debug(
                            f"✅ best_ask актуален для {symbol} BUY: "
                            f"best_ask={best_ask:.2f}, current={current_price:.2f}, diff={ask_price_diff_pct:.3%}"
                        )
                    else:
                        logger.debug(
                            f"📊 [LIMIT_PRICE] {symbol} BUY: best_ask устарел (diff={ask_price_diff_pct:.3%}), "
                            f"используем current_price={current_price:.2f} вместо best_ask={best_ask:.2f}"
                        )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для BUY используем best_ask (лучшая цена продажи)
                # Для скальпинга нужно быстрое исполнение, поэтому используем best_ask или немного выше
                # НЕ используем best_bid - это ставит ордер далеко от рынка!
                if use_best_ask and best_ask > 0:
                    # ✅ НОВОЕ: Используем адаптивный offset на основе спреда, если доступен
                    if adaptive_offset_pct is not None:
                        limit_price = best_ask * (1 + adaptive_offset_pct / 100.0)
                        logger.debug(
                            f"💰 Для {symbol} BUY: используем адаптивный offset {adaptive_offset_pct:.4f}% "
                            f"(spread={spread_pct:.4f}%) для гарантии исполнения "
                            f"(best_ask={best_ask:.2f} → limit_price={limit_price:.2f})"
                        )
                    elif offset_percent == 0.0:
                        # ✅ ИСПРАВЛЕНО: Если offset=0, используем минимальный offset 0.01% для гарантии исполнения
                        min_offset = (
                            0.01  # Минимальный offset 0.01% для гарантии исполнения
                        )
                        limit_price = best_ask * (1 + min_offset / 100.0)
                        logger.debug(
                            f"💰 Для {symbol} BUY: offset=0, используем минимальный offset {min_offset}% "
                            f"для гарантии исполнения (best_ask={best_ask:.2f} → limit_price={limit_price:.2f})"
                        )
                    else:
                        # Используем offset из конфига (fallback)
                        limit_price = best_ask * (1 + offset_percent / 100.0)
                        logger.debug(
                            f"💰 Для {symbol} BUY: используем offset из конфига {offset_percent:.3f}% "
                            f"(best_ask={best_ask:.2f} → limit_price={limit_price:.2f})"
                        )
                elif current_price > 0:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: best_ask устарел, используем current_price (НЕ signal_price!)
                    # signal_price может быть еще более устаревшим, что приводит к ордерам ниже рынка
                    min_offset = max(offset_percent, 0.01)  # Минимальный offset 0.01%
                    limit_price = current_price * (1 + min_offset / 100.0)

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем, что цена >= best_ask (если доступен)
                    # Для BUY ордер должен быть выше или равен best_ask для гарантии исполнения
                    if best_ask > 0 and limit_price < best_ask:
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} BUY ({limit_price:.2f}) ниже best_ask ({best_ask:.2f}), "
                            f"корректируем до best_ask + offset"
                        )
                        limit_price = best_ask * (1 + min_offset / 100.0)

                    logger.info(
                        f"💰 Используем current_price для {symbol} BUY (best_ask устарел): "
                        f"current={current_price:.2f}, offset={min_offset:.3f}%, "
                        f"limit_price={limit_price:.2f} (>= best_ask={best_ask:.2f})"
                    )
                elif base_price > 0:
                    # ✅ Fallback: используем base_price только если current_price недоступен
                    min_offset = max(offset_percent, 0.01)  # Минимальный offset 0.01%
                    limit_price = base_price * (1 + min_offset / 100.0)

                    # ✅ Проверяем, что цена >= best_ask (если доступен)
                    if best_ask > 0 and limit_price < best_ask:
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} BUY ({limit_price:.2f}) ниже best_ask ({best_ask:.2f}), "
                            f"корректируем до best_ask + offset"
                        )
                        limit_price = best_ask * (1 + min_offset / 100.0)

                    logger.debug(
                        f"💰 Используем base_price (fallback) для {symbol} BUY: "
                        f"base={base_price:.2f}, offset={min_offset:.3f}%, "
                        f"limit_price={limit_price:.2f}"
                    )
                else:
                    # Fallback: используем best_ask даже если устарел
                    limit_price = (
                        best_ask * (1 + offset_percent / 100.0) if best_ask > 0 else 0.0
                    )
                    logger.warning(
                        f"⚠️ Fallback для {symbol} BUY: используем best_ask={best_ask:.2f} "
                        f"(current_price недоступен)"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Финальная проверка для BUY
                # 1. Проверяем лимит биржи max_buy_price
                # 2. Убеждаемся, что цена >= best_ask (для гарантии исполнения)
                # 3. Убеждаемся, что цена >= best_bid (защита от ошибок)

                # Проверка 1: Лимит биржи
                if limit_price > max_buy_price:
                    logger.warning(
                        f"⚠️ Лимитная цена для {symbol} BUY ({limit_price:.2f}) превышает лимит биржи ({max_buy_price:.2f}), "
                        f"корректируем до {max_buy_price:.2f}"
                    )
                    limit_price = max_buy_price

                # Проверка 2: Должна быть >= best_ask для гарантии исполнения
                if best_ask > 0 and limit_price < best_ask:
                    logger.warning(
                        f"⚠️ Лимитная цена для {symbol} BUY ({limit_price:.2f}) ниже best_ask ({best_ask:.2f}), "
                        f"корректируем до best_ask + минимальный offset"
                    )
                    min_offset = max(offset_percent, 0.01)
                    limit_price = best_ask * (1 + min_offset / 100.0)

                # Проверка 3: Должна быть >= best_bid (защита от критических ошибок)
                if best_bid > 0 and limit_price < best_bid:
                    logger.error(
                        f"❌ КРИТИЧЕСКАЯ ОШИБКА: Лимитная цена для {symbol} BUY ({limit_price:.2f}) ниже best_bid ({best_bid:.2f})! "
                        f"Это невозможно для BUY ордера. Корректируем до best_ask ({best_ask:.2f})"
                    )
                    limit_price = best_ask if best_ask > 0 else (best_bid * 1.001)
            else:  # sell
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для SELL проверяем актуальность best_bid
                # Проблема: best_bid из стакана может быть устаревшим (например, $90,619 vs текущая $90,100)
                # Решение: Используем best_bid только если он близок к current_price, иначе используем current_price

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем актуальность best_bid
                # Увеличиваем порог до 0.5% для более гибкой работы
                use_best_bid = False
                if best_bid > 0 and current_price > 0:
                    bid_price_diff_pct = abs(best_bid - current_price) / current_price
                    # ✅ ИСПРАВЛЕНО: Используем best_bid если разница < 0.5% (было 0.1%)
                    if bid_price_diff_pct < 0.005:
                        use_best_bid = True
                        logger.debug(
                            f"✅ best_bid актуален для {symbol} SELL: "
                            f"best_bid={best_bid:.2f}, current={current_price:.2f}, diff={bid_price_diff_pct:.3%}"
                        )
                    else:
                        logger.debug(
                            f"📊 [LIMIT_PRICE] {symbol} SELL: best_bid устарел (diff={bid_price_diff_pct:.3%}), "
                            f"используем current_price={current_price:.2f} вместо best_bid={best_bid:.2f}"
                        )

                # ✅ ИСПРАВЛЕНО: Для SELL используем best_bid только если он актуален, иначе current_price
                if use_best_bid:
                    # ✅ НОВОЕ: Используем адаптивный offset на основе спреда, если доступен
                    if adaptive_offset_pct is not None:
                        limit_price = best_bid * (1 - adaptive_offset_pct / 100.0)
                        logger.debug(
                            f"💰 Для {symbol} SELL: используем адаптивный offset {adaptive_offset_pct:.4f}% "
                            f"(spread={spread_pct:.4f}%) для гарантии исполнения "
                            f"(best_bid={best_bid:.2f} → limit_price={limit_price:.2f})"
                        )
                    else:
                        # Используем offset из конфига (fallback)
                        limit_price = best_bid * (1 - offset_percent / 100.0)
                        logger.debug(
                            f"💰 Для {symbol} SELL: используем offset из конфига {offset_percent:.3f}% "
                            f"(best_bid={best_bid:.2f} → limit_price={limit_price:.2f})"
                        )
                elif current_price > 0:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: best_bid устарел, используем current_price (НЕ signal_price!)
                    # signal_price может быть еще более устаревшим, что приводит к ордерам выше рынка
                    min_offset = max(offset_percent, 0.01)  # Минимальный offset 0.01%
                    limit_price = current_price * (1 - min_offset / 100.0)

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем, что цена <= best_bid (если доступен)
                    # Для SELL ордер должен быть ниже или равен best_bid для гарантии исполнения
                    if best_bid > 0 and limit_price > best_bid:
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} SELL ({limit_price:.2f}) выше best_bid ({best_bid:.2f}), "
                            f"корректируем до best_bid - offset"
                        )
                        limit_price = best_bid * (1 - min_offset / 100.0)

                    logger.info(
                        f"💰 Используем current_price для {symbol} SELL (best_bid устарел): "
                        f"current={current_price:.2f}, offset={min_offset:.3f}%, "
                        f"limit_price={limit_price:.2f} (<= best_bid={best_bid:.2f})"
                    )
                elif base_price > 0:
                    # ✅ Fallback: используем base_price только если current_price недоступен
                    min_offset = max(offset_percent, 0.01)
                    limit_price = base_price * (1 - min_offset / 100.0)

                    # ✅ Проверяем, что цена <= best_bid (если доступен)
                    if best_bid > 0 and limit_price > best_bid:
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} SELL ({limit_price:.2f}) выше best_bid ({best_bid:.2f}), "
                            f"корректируем до best_bid - offset"
                        )
                        limit_price = best_bid * (1 - min_offset / 100.0)

                    logger.debug(
                        f"💰 Используем base_price (fallback) для {symbol} SELL: "
                        f"base={base_price:.2f}, offset={min_offset:.3f}%, "
                        f"limit_price={limit_price:.2f}"
                    )
                else:
                    # Fallback: используем best_bid даже если устарел
                    limit_price = (
                        best_bid * (1 - offset_percent / 100.0) if best_bid > 0 else 0.0
                    )
                    logger.warning(
                        f"⚠️ Fallback для {symbol} SELL: используем best_bid={best_bid:.2f} "
                        f"(current_price недоступен)"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Финальная проверка для SELL
                # 1. Проверяем лимит биржи min_sell_price
                # 2. Убеждаемся, что цена <= best_bid (для гарантии исполнения)
                # 3. Убеждаемся, что цена <= best_ask (защита от ошибок)

                # Проверка 1: Лимит биржи
                if use_best_bid and best_bid > 0:
                    # best_bid актуален, можно использовать min_sell_price
                    if limit_price < min_sell_price:
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} SELL ({limit_price:.2f}) ниже лимита биржи ({min_sell_price:.2f}), "
                            f"корректируем до {min_sell_price * 1.0001:.2f}"
                        )
                        limit_price = (
                            min_sell_price * 1.0001
                        )  # Немного выше лимита для безопасности
                elif current_price > 0:
                    # best_bid устарел, НЕ используем min_sell_price (он тоже устарел)
                    logger.debug(
                        f"💰 Не используем min_sell_price для {symbol} SELL "
                        f"(best_bid устарел, min_sell_price тоже устарел)"
                    )
                else:
                    # Fallback: используем min_sell_price
                    if limit_price < min_sell_price:
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} SELL ({limit_price:.2f}) ниже лимита биржи ({min_sell_price:.2f}), "
                            f"корректируем до {min_sell_price * 1.0001:.2f}"
                        )
                        limit_price = min_sell_price * 1.0001

                # Проверка 2: Должна быть <= best_bid для гарантии исполнения
                if best_bid > 0 and limit_price > best_bid:
                    logger.warning(
                        f"⚠️ Лимитная цена для {symbol} SELL ({limit_price:.2f}) выше best_bid ({best_bid:.2f}), "
                        f"корректируем до best_bid - минимальный offset"
                    )
                    min_offset = max(offset_percent, 0.01)
                    limit_price = best_bid * (1 - min_offset / 100.0)

                # Проверка 3: Должна быть <= best_ask (защита от критических ошибок)
                if best_ask > 0 and limit_price > best_ask:
                    logger.error(
                        f"❌ КРИТИЧЕСКАЯ ОШИБКА: Лимитная цена для {symbol} SELL ({limit_price:.2f}) выше best_ask ({best_ask:.2f})! "
                        f"Это невозможно для SELL ордера. Корректируем до best_bid ({best_bid:.2f})"
                    )
                    limit_price = best_bid if best_bid > 0 else (best_ask * 0.999)

            # ✅ ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: Убеждаемся, что цена в допустимом диапазоне
            # Финальная проверка лимитов биржи уже выполнена выше

            # ✅ ИСПРАВЛЕНО: Проверяем разницу между limit_price и base_price (0.2% для скальпинга)
            price_diff_pct = (
                abs(limit_price - base_price) / base_price * 100
                if base_price > 0
                else 0
            )
            if (
                price_diff_pct > 0.2
            ):  # ✅ ИСПРАВЛЕНО: Если разница > 0.2% - это проблема для скальпинга!
                logger.error(
                    f"❌ КРИТИЧЕСКАЯ ОШИБКА: Лимитная цена для {symbol} {side} слишком далеко от базовой! "
                    f"limit_price={limit_price:.2f}, base_price={base_price:.2f}, "
                    f"разница={price_diff_pct:.2f}%, offset={offset_percent:.3f}%, режим={regime or 'N/A'}"
                )
                # ✅ НОВОЕ: Корректируем цену до безопасного значения
                if side.lower() == "buy":
                    limit_price = base_price * 1.001  # Максимум 0.1% выше
                else:
                    limit_price = base_price * 0.999  # Максимум 0.1% ниже
                logger.warning(
                    f"⚠️ Цена скорректирована до безопасного значения: {limit_price:.2f} "
                    f"(было {limit_price:.2f}, разница была {price_diff_pct:.2f}%)"
                )

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Логируем все детали расчета лимитной цены
            # ✅ НОВОЕ: Добавляем информацию о спреде и адаптивном offset
            offset_used = (
                adaptive_offset_pct
                if adaptive_offset_pct is not None
                else offset_percent
            )
            offset_type = "adaptive" if adaptive_offset_pct is not None else "config"
            logger.info(
                f"💰 Лимитная цена для {symbol} {side}: {limit_price:.2f} "
                f"(best_bid={best_bid:.2f}, best_ask={best_ask:.2f}, base_price={base_price:.2f}, "
                f"signal_price={signal_price if signal_price else 'N/A'}, current_price={current_price:.2f}, "
                f"spread={spread:.6f} ({spread_pct:.4f}%), offset={offset_used:.4f}% ({offset_type}), "
                f"режим={regime or 'default'}, разница={price_diff_pct:.2f}%, "
                f"лимиты: max_buy={max_buy_price:.2f}, min_sell={min_sell_price:.2f})"
            )
            logger.debug(
                f"🔍 [CALCULATE_LIMIT_PRICE] {symbol} {side}: "
                f"limit_price={limit_price:.2f}, best_bid={best_bid:.2f}, best_ask={best_ask:.2f}, "
                f"current_price={current_price:.2f}, spread={spread:.6f} ({spread_pct:.4f}%), "
                f"offset={offset_used:.4f}% ({offset_type}), config_offset={offset_percent:.3f}%, "
                f"spread_bid={abs(best_bid - current_price) / current_price * 100 if best_bid > 0 and current_price > 0 else 0:.3f}%, "
                f"spread_ask={abs(best_ask - current_price) / current_price * 100 if best_ask > 0 and current_price > 0 else 0:.3f}%"
            )
            return limit_price

        except Exception as e:
            logger.error(f"Ошибка расчета лимитной цены для {symbol}: {e}")
            return 0.0

    async def _place_market_order(
        self, symbol: str, side: str, size: float
    ) -> Dict[str, Any]:
        """Размещение рыночного ордера"""
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка минимального размера ордера (OKX требует ≥ 0.01)
            # Размер приходит в монетах, нужно конвертировать в контракты для проверки
            try:
                inst_details = await self.client.get_instrument_details(symbol)
                ct_val = float(inst_details.get("ctVal", 0.01))
                min_sz = float(inst_details.get("minSz", 0.01))

                # Конвертируем размер из монет в контракты
                size_in_contracts = size / ct_val if ct_val > 0 else 0

                if size_in_contracts < min_sz:
                    error_msg = f"❌ Размер ордера {size:.6f} монет ({size_in_contracts:.6f} контрактов) меньше минимального {min_sz:.6f} контрактов для {symbol}"
                    logger.error(error_msg)
                    return {"success": False, "error": error_msg, "code": "35027"}
            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось проверить минимальный размер для {symbol}: {e}, пропускаем проверку"
                )

            logger.info(f"📈 Размещение рыночного ордера: {symbol} {side} {size:.6f}")

            # Для метрик: зафиксируем лучшие цены до отправки
            best_bid = best_ask = None
            try:
                limits = await self.client.get_price_limits(symbol)
                best_bid = (
                    float(limits.get("best_bid"))
                    if limits and limits.get("best_bid")
                    else None
                )
                best_ask = (
                    float(limits.get("best_ask"))
                    if limits and limits.get("best_ask")
                    else None
                )
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось получить лучшие цены перед market-ордером {symbol}: {e}"
                )

            # ✅ FIX: Замер latency (send_time → fill_time)
            import time as _time

            send_time = _time.perf_counter()

            result = await self.client.place_futures_order(
                symbol=symbol, side=side, size=size, order_type="market"
            )

            fill_time = _time.perf_counter()
            latency_ms = int((fill_time - send_time) * 1000)

            if result.get("code") == "0":
                order_id = result.get("data", [{}])[0].get("ordId")
                logger.info(f"✅ Рыночный ордер размещен: {order_id}")

                # Метрики: учёт market-ордеров и проскальзывания (если есть fill price)
                try:
                    self.execution_stats["market_orders"] += 1
                    data0 = (result.get("data") or [{}])[0]
                    fill_px = None
                    for key in ("avgPx", "fillPx", "fillPrice"):
                        if key in data0 and data0.get(key):
                            try:
                                fill_px = float(data0.get(key))
                                break
                            except (TypeError, ValueError):
                                continue
                    if fill_px and best_bid and best_ask:
                        if side.lower() in ("buy", "long"):
                            ref = best_ask
                            slippage_bps = (fill_px - ref) / ref * 1e4
                        else:
                            ref = best_bid
                            slippage_bps = (ref - fill_px) / ref * 1e4
                        self.execution_stats["total_slippage_bps"] += float(
                            slippage_bps
                        )
                        self.execution_stats["slippage_samples"] += 1
                        logger.debug(
                            f"📏 Slippage {symbol} {side}: {slippage_bps:.2f} bps (ref={ref:.4f}, fill={fill_px:.4f})"
                        )
                        # ✅ FIX: FILL log с latency и slippage
                        logger.info(
                            f"FILL {symbol} latency={latency_ms}ms slippage={slippage_bps:.2f}bps"
                        )
                        if latency_ms > 300:
                            logger.warning(f"FILL_LATENCY_HIGH {symbol} {latency_ms}ms")

                        # ✅ НОВОЕ: Логирование исполнения ордера (fill) в CSV
                        if self.performance_tracker:
                            try:
                                self.performance_tracker.record_order(
                                    symbol=symbol,
                                    side=side,
                                    order_type="market",
                                    order_id=order_id or "",
                                    size=size,
                                    price=None,
                                    status="filled",
                                    fill_price=fill_px,
                                    fill_size=size,
                                    execution_time_ms=latency_ms,
                                    slippage=slippage_bps / 100.0
                                    if slippage_bps
                                    else None,  # bps to percent
                                )
                                logger.debug(
                                    f"✅ OrderExecutor: Исполнение ордера {order_id} записано в CSV"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"⚠️ OrderExecutor: Ошибка записи исполнения ордера в CSV: {e}"
                                )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Не удалось обновить метрики slippage для {symbol}: {e}"
                    )

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_type": "market",
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "timestamp": datetime.now(),
                }
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка размещения рыночного ордера: {error_msg}")

                return {"success": False, "error": error_msg, "order_type": "market"}

        except Exception as e:
            logger.error(f"Ошибка размещения рыночного ордера: {e}")
            return {"success": False, "error": str(e)}

    async def _place_limit_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        regime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Размещение лимитного ордера с fallback на рыночный
        """
        try:
            # ✅ ИСПРАВЛЕНО: Получаем post_only из конфига с учетом режима
            order_executor_config = getattr(self.scalping_config, "order_executor", {})
            limit_order_config = order_executor_config.get("limit_order", {})

            # Получаем post_only по режиму
            # ✅ FIX: post_only=True по умолчанию для экономии комиссий (0.02% вместо 0.05%)
            if regime:
                regime_config = limit_order_config.get("by_regime", {}).get(
                    regime.lower(), {}
                )
                post_only = regime_config.get(
                    "post_only", limit_order_config.get("post_only", True)
                )
            else:
                post_only = limit_order_config.get("post_only", True)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): Проверка свежести цены перед POST_ONLY
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): Отключение POST_ONLY при высокой волатильности (>0.5%)
            price_limits = None  # Инициализируем для использования ниже
            if post_only:
                # Проверяем свежесть цены
                price_limits = await self.client.get_price_limits(symbol)
                if price_limits:
                    price_timestamp = price_limits.get("timestamp", 0)
                    current_price = price_limits.get("current_price", 0)

                    if price_timestamp > 0:
                        price_age = time.time() - price_timestamp
                        if price_age > 1.0:  # Цена старше 1 секунды
                            logger.warning(
                                f"⚠️ Цена для {symbol} устарела ({price_age:.2f} сек), "
                                f"отключаем POST_ONLY для быстрого исполнения"
                            )
                            post_only = False

                        # Проверяем расхождение между лимитной ценой и текущей ценой
                        if current_price > 0 and price > 0:
                            price_diff_pct = (
                                abs(price - current_price) / current_price * 100.0
                            )
                            if price_diff_pct > 0.5:  # Расхождение > 0.5%
                                logger.warning(
                                    f"⚠️ Лимитная цена {price:.2f} отличается от текущей {current_price:.2f} "
                                    f"на {price_diff_pct:.2f}%, отключаем POST_ONLY"
                                )
                                post_only = False

                    # ✅ ИСПРАВЛЕНИЕ: Проверка волатильности для отключения POST_ONLY
                    volatility = None
                    if self.data_registry:
                        try:
                            # Получаем ATR из DataRegistry
                            atr = await self.data_registry.get_indicator(symbol, "atr")
                            if atr and current_price > 0:
                                # Рассчитываем волатильность как ATR в процентах от цены
                                volatility = (atr / current_price) * 100.0
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Не удалось получить ATR для расчета волатильности: {e}"
                            )

                    # Альтернативный способ получения волатильности из regime_manager
                    if volatility is None and self.signal_generator:
                        try:
                            regime_manager = (
                                self.signal_generator.regime_managers.get(symbol)
                                or self.signal_generator.regime_manager
                            )
                            if regime_manager and hasattr(
                                regime_manager, "last_volatility"
                            ):
                                volatility = regime_manager.last_volatility
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Не удалось получить волатильность из regime_manager: {e}"
                            )

                    # Отключаем POST_ONLY при высокой волатильности (>0.5%)
                    if volatility is not None and volatility > 0.5:
                        logger.warning(
                            f"⚠️ Высокая волатильность для {symbol} ({volatility:.2f}% > 0.5%), "
                            f"отключаем POST_ONLY для быстрого исполнения"
                        )
                        post_only = False
                    elif volatility is not None:
                        logger.debug(
                            f"✅ Волатильность для {symbol}: {volatility:.2f}% (POST_ONLY разрешен)"
                        )

            if post_only:
                logger.info(f"POST_ONLY enabled {symbol} (maker fee 0.02%)")
            else:
                logger.info(
                    f"POST_ONLY disabled {symbol} (быстрое исполнение, taker fee 0.05%)"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем ценовые лимиты перед размещением ордера
            # ✅ ИСПРАВЛЕНИЕ: Используем уже полученные price_limits из проверки свежести цены
            if not price_limits:
                price_limits = await self.client.get_price_limits(symbol)
            if price_limits:
                max_buy_price = price_limits.get("max_buy_price", 0)
                min_sell_price = price_limits.get("min_sell_price", 0)

                if side.lower() == "buy" and max_buy_price > 0:
                    if price > max_buy_price:
                        # ✅ ИСПРАВЛЕНО: Корректируем с небольшим запасом (0.999) чтобы избежать ошибки 51006
                        corrected_price = max_buy_price * 0.999
                        logger.warning(
                            f"⚠️ Цена BUY ордера {price:.2f} превышает лимит биржи {max_buy_price:.2f}, "
                            f"корректируем до {corrected_price:.2f} (0.999 от лимита)"
                        )
                        price = corrected_price
                elif side.lower() == "sell" and min_sell_price > 0:
                    if price < min_sell_price:
                        # ✅ ИСПРАВЛЕНО: Корректируем с небольшим запасом (1.001) чтобы избежать ошибки 51006
                        corrected_price = min_sell_price * 1.001
                        logger.warning(
                            f"⚠️ Цена SELL ордера {price:.2f} ниже лимита биржи {min_sell_price:.2f}, "
                            f"корректируем до {corrected_price:.2f} (1.001 от лимита)"
                        )
                        price = corrected_price

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка минимального размера ордера (OKX требует ≥ 0.01)
            # Размер приходит в монетах, нужно конвертировать в контракты для проверки
            try:
                inst_details = await self.client.get_instrument_details(symbol)
                ct_val = float(inst_details.get("ctVal", 0.01))
                min_sz = float(inst_details.get("minSz", 0.01))

                # Конвертируем размер из монет в контракты
                size_in_contracts = size / ct_val if ct_val > 0 else 0

                if size_in_contracts < min_sz:
                    error_msg = f"❌ Размер ордера {size:.6f} монет ({size_in_contracts:.6f} контрактов) меньше минимального {min_sz:.6f} контрактов для {symbol}"
                    logger.error(error_msg)
                    return {"success": False, "error": error_msg, "code": "35027"}
            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось проверить минимальный размер для {symbol}: {e}, пропускаем проверку"
                )

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Логируем все детали размещения ордера
            logger.info(
                f"📊 Размещение лимитного ордера: {symbol} {side} {size:.6f} @ {price:.2f} "
                f"(post_only={post_only})"
            )
            logger.debug(
                f"🔍 [PLACE_LIMIT_ORDER] {symbol} {side}: "
                f"size={size:.6f}, price={price:.2f}, post_only={post_only}, regime={regime or 'N/A'}"
            )

            # ✅ НОВОЕ: Генерируем уникальный clOrdId если не передан
            # OKX требует: максимум 32 символа, только буквы и цифры (alphanumeric)
            symbol_clean = symbol.replace("-", "").replace("_", "")[
                :8
            ]  # Убираем дефисы и подчеркивания, ограничиваем до 8 символов
            side_short = side[:1].upper()  # "b" или "s"
            timestamp_short = str(int(time.time() * 1000))[
                -10:
            ]  # Последние 10 цифр timestamp
            uuid_short = uuid.uuid4().hex[:8]  # 8 символов UUID
            cl_ord_id = f"{symbol_clean}{side_short}{timestamp_short}{uuid_short}"[
                :32
            ]  # Максимум 32 символа

            # ✅ НОВОЕ: Валидация параметров перед размещением
            if price <= 0:
                error_msg = f"❌ Неверная цена для ордера {symbol}: {price}"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}

            if size <= 0:
                error_msg = f"❌ Неверный размер для ордера {symbol}: {size}"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}

            # ✅ ИСПРАВЛЕНИЕ #6: Проверяем лимиты биржи ПЕРЕД размещением ордера
            try:
                price_limits = await self.client.get_price_limits(symbol)
                if price_limits:
                    max_buy_price = price_limits.get("max_buy_price", 0)
                    min_sell_price = price_limits.get("min_sell_price", 0)

                    if side.lower() == "buy" and max_buy_price > 0:
                        if price > max_buy_price:
                            logger.warning(
                                f"⚠️ Цена BUY {price:.2f} превышает лимит биржи {max_buy_price:.2f}, "
                                f"корректируем до {max_buy_price * 0.9999:.2f} (0.01% ниже лимита)"
                            )
                            price = max_buy_price * 0.9999
                    elif side.lower() == "sell" and min_sell_price > 0:
                        if price < min_sell_price:
                            logger.warning(
                                f"⚠️ Цена SELL {price:.2f} ниже лимита биржи {min_sell_price:.2f}, "
                                f"корректируем до {min_sell_price * 1.0001:.2f} (0.01% выше лимита)"
                            )
                            price = min_sell_price * 1.0001
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось проверить лимиты биржи перед размещением: {e}"
                )

            result = await self.client.place_futures_order(
                symbol=symbol,
                side=side,
                size=size,
                price=price,
                order_type="limit",
                post_only=post_only,
                cl_ord_id=cl_ord_id,  # ✅ НОВОЕ: Передаем уникальный clOrdId
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Инициализируем order_id как None
            order_id = None

            if result.get("code") == "0":
                order_id = result.get("data", [{}])[0].get("ordId")
                logger.info(f"✅ Лимитный ордер размещен: {order_id}")
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Возвращаем результат сразу после успешного размещения
                # Метрики: учитываем тип лимитного ордера как maker/other по флагу post_only
                try:
                    if post_only:
                        self.execution_stats["limit_orders_maker"] += 1
                    else:
                        self.execution_stats["limit_orders_other"] += 1
                except Exception:
                    pass

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_type": "limit",
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "price": price,
                    "timestamp": datetime.now(),
                }
            elif result.get("code") == "1" or result.get("code") != "0":
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обрабатываем ошибку ценовых лимитов
                error_data = result.get("data", [{}])[0] if result.get("data") else {}
                error_code = error_data.get("sCode", "")
                error_msg = error_data.get("sMsg", "")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ошибка 51006: Order price is not within the price limit
                # Проверяем код ошибки и сообщение более гибко
                if (
                    error_code == "51006"
                    or "51006" in str(error_code)
                    or "price limit" in error_msg.lower()
                    or "price is not within" in error_msg.lower()
                ):
                    # Извлекаем лимиты из сообщения об ошибке
                    import re

                    max_buy_match = re.search(
                        r"max buy price:\s*([\d,]+\.?\d*)", error_msg, re.IGNORECASE
                    )
                    min_sell_match = re.search(
                        r"min sell price:\s*([\d,]+\.?\d*)", error_msg, re.IGNORECASE
                    )

                    if max_buy_match or min_sell_match:
                        max_buy_from_error = (
                            float(max_buy_match.group(1).replace(",", ""))
                            if max_buy_match
                            else None
                        )
                        min_sell_from_error = (
                            float(min_sell_match.group(1).replace(",", ""))
                            if min_sell_match
                            else None
                        )

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Корректируем цену на основе реальных лимитов биржи
                        # Используем небольшой offset (0.1%) для гарантии прохождения
                        corrected_price = None
                        if side.lower() == "buy" and max_buy_from_error:
                            if price > max_buy_from_error:
                                corrected_price = (
                                    max_buy_from_error * 0.999
                                )  # 0.1% ниже лимита для безопасности
                                logger.warning(
                                    f"⚠️ Цена BUY {price:.2f} превышает лимит биржи {max_buy_from_error:.2f}, "
                                    f"корректируем до {corrected_price:.2f} (0.1% ниже лимита)"
                                )
                        elif side.lower() == "sell" and min_sell_from_error:
                            if price < min_sell_from_error:
                                corrected_price = (
                                    min_sell_from_error * 1.001
                                )  # 0.1% выше лимита для безопасности
                                logger.warning(
                                    f"⚠️ Цена SELL {price:.2f} ниже лимита биржи {min_sell_from_error:.2f}, "
                                    f"корректируем до {corrected_price:.2f} (0.1% выше лимита)"
                                )

                        # ✅ КРИТИЧЕСКОЕ: Пробуем разместить ордер с исправленной ценой
                        if corrected_price is not None:
                            logger.info(
                                f"🔄 Повторная попытка размещения лимитного ордера с исправленной ценой: "
                                f"{symbol} {side} {size:.6f} @ {corrected_price:.2f}"
                            )
                            # ✅ НОВОЕ: Генерируем уникальный clOrdId для retry (только буквы и цифры, макс 32 символа)
                            symbol_clean_retry = symbol.replace("-", "").replace(
                                "_", ""
                            )[:8]
                            side_short_retry = side[:1].upper()
                            timestamp_short_retry = str(int(time.time() * 1000))[-10:]
                            uuid_short_retry = uuid.uuid4().hex[:8]
                            cl_ord_id_retry = f"{symbol_clean_retry}{side_short_retry}{timestamp_short_retry}{uuid_short_retry}"[
                                :32
                            ]

                            retry_result = await self.client.place_futures_order(
                                symbol=symbol,
                                side=side,
                                size=size,
                                price=corrected_price,
                                order_type="limit",
                                post_only=post_only,
                                cl_ord_id=cl_ord_id_retry,  # ✅ НОВОЕ: Передаем исправленный clOrdId
                            )
                            if retry_result.get("code") == "0":
                                order_id = retry_result.get("data", [{}])[0].get(
                                    "ordId"
                                )
                                # ✅ НОВОЕ: Логирование размещения лимитного ордера (retry) в CSV
                                if self.performance_tracker:
                                    try:
                                        self.performance_tracker.record_order(
                                            symbol=symbol,
                                            side=side,
                                            order_type="limit",
                                            order_id=order_id or "",
                                            size=size,
                                            price=corrected_price,
                                            status="placed",
                                        )
                                        logger.debug(
                                            f"✅ OrderExecutor: Размещение лимитного ордера (retry) {order_id} записано в CSV"
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"⚠️ OrderExecutor: Ошибка записи размещения лимитного ордера (retry) в CSV: {e}"
                                        )
                                logger.info(
                                    f"✅ Лимитный ордер размещен с исправленной ценой: {order_id}"
                                )
                                return {
                                    "success": True,
                                    "order_id": order_id,
                                    "order_type": "limit",
                                    "price": corrected_price,
                                    "original_price": price,
                                    "price_corrected": True,
                                }
                            else:
                                # Если скорректированная цена тоже не прошла, логируем и пробуем рыночный ордер
                                retry_error = (
                                    retry_result.get("data", [{}])[0]
                                    if retry_result.get("data")
                                    else {}
                                )
                                retry_error_msg = retry_error.get(
                                    "sMsg",
                                    retry_result.get("msg", "Неизвестная ошибка"),
                                )
                                logger.warning(
                                    f"⚠️ Скорректированная цена ({corrected_price:.2f}) также не прошла: {retry_error_msg}, "
                                    f"пробуем рыночный ордер"
                                )
                                # Fallback на рыночный ордер
                                market_result = await self._place_market_order(
                                    symbol, side, size
                                )
                                if market_result.get("success"):
                                    logger.info(
                                        f"✅ Рыночный ордер размещен как fallback (лимитный был отклонен)"
                                    )
                                return market_result
                        else:
                            # Если не удалось скорректировать цену, пробуем рыночный ордер
                            logger.warning(
                                f"⚠️ Не удалось скорректировать цену для {symbol} {side}, пробуем рыночный ордер"
                            )
                            market_result = await self._place_market_order(
                                symbol, side, size
                            )
                            if market_result.get("success"):
                                logger.info(
                                    f"✅ Рыночный ордер размещен как fallback (лимитный был отклонен)"
                                )
                            return market_result

                # Метрики: учитываем тип лимитного ордера как maker/other по флагу post_only
                try:
                    if post_only:
                        self.execution_stats["limit_orders_maker"] += 1
                    else:
                        self.execution_stats["limit_orders_other"] += 1
                except Exception:
                    pass

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если order_id не был установлен (ордер не размещен), возвращаем ошибку
                if order_id is None:
                    logger.error(
                        f"❌ Лимитный ордер не был размещен для {symbol} {side}: "
                        f"code={result.get('code')}, msg={error_msg}"
                    )
                    return {
                        "success": False,
                        "error": f"Ордер не размещен: {error_msg}",
                        "error_code": error_code,
                        "order_type": "limit",
                        "symbol": symbol,
                        "side": side,
                        "size": size,
                        "price": price,
                    }

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_type": "limit",
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "price": price,
                    "timestamp": datetime.now(),
                }
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                error_code = result.get("code", "")
                error_data = result.get("data", [])

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Парсим лимиты из ошибки API (51006)
                parsed_min_sell = None
                parsed_max_buy = None

                if error_data and len(error_data) > 0:
                    s_msg = error_data[0].get("sMsg", "")
                    # ✅ Парсим лимиты из сообщения: "Order price is not within the price limit (max buy price: 103,155.9, min sell price: 101,133.2)"
                    max_buy_match = re.search(
                        r"max buy price:\s*([\d,]+\.?\d*)", s_msg, re.IGNORECASE
                    )
                    min_sell_match = re.search(
                        r"min sell price:\s*([\d,]+\.?\d*)", s_msg, re.IGNORECASE
                    )

                    if max_buy_match:
                        try:
                            parsed_max_buy = float(
                                max_buy_match.group(1).replace(",", "")
                            )
                            logger.info(
                                f"📊 Парсирован max buy price из ошибки: {parsed_max_buy:.2f}"
                            )
                        except Exception as e:
                            logger.debug(f"Не удалось парсить max buy price: {e}")

                    if min_sell_match:
                        try:
                            parsed_min_sell = float(
                                min_sell_match.group(1).replace(",", "")
                            )
                            logger.info(
                                f"📊 Парсирован min sell price из ошибки: {parsed_min_sell:.2f}"
                            )
                        except Exception as e:
                            logger.debug(f"Не удалось парсить min sell price: {e}")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем код ошибки
                # Если ошибка связана с лимитом цены (51006) - пробуем скорректировать цену или использовать рыночный ордер
                if (
                    "51006" in str(error_msg)
                    or "51006" in str(error_code)
                    or "price limit" in error_msg.lower()
                    or "price is not within" in error_msg.lower()
                ):
                    logger.warning(
                        f"⚠️ Лимитный ордер отклонен из-за лимита цены (51006): {error_msg}"
                    )

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если получили лимиты из ошибки, пробуем скорректировать цену
                    # Используем более консервативный offset (0.1%) для гарантии прохождения
                    corrected_price = None
                    if side.lower() == "sell" and parsed_min_sell:
                        # Для SELL: цена должна быть >= min_sell_price
                        # ✅ ИСПРАВЛЕНО: Используем 0.1% выше лимита для безопасности
                        corrected_price = parsed_min_sell * 1.001  # 0.1% выше лимита
                        # ✅ КРИТИЧЕСКОЕ: Всегда пробуем скорректированную цену, даже если она выше старой
                        # Проблема была в том, что старая цена была неправильной (ниже лимита)
                        logger.info(
                            f"🔄 Пробуем скорректированную цену для {symbol} SELL: {price:.2f} → {corrected_price:.2f} "
                            f"(min_sell={parsed_min_sell:.2f}, offset=0.1%)"
                        )
                    elif side.lower() == "buy" and parsed_max_buy:
                        # Для BUY: цена должна быть <= max_buy_price
                        # ✅ ИСПРАВЛЕНО: Используем 0.1% ниже лимита для безопасности
                        corrected_price = parsed_max_buy * 0.999  # 0.1% ниже лимита
                        logger.info(
                            f"🔄 Пробуем скорректированную цену для {symbol} BUY: {price:.2f} → {corrected_price:.2f} "
                            f"(max_buy={parsed_max_buy:.2f}, offset=0.1%)"
                        )

                    # ✅ КРИТИЧЕСКОЕ: Пробуем разместить ордер с исправленной ценой
                    if corrected_price is not None:
                        # Пробуем разместить ордер с скорректированной ценой
                        # ✅ Генерируем уникальный clOrdId для retry
                        symbol_clean_retry = symbol.replace("-", "").replace("_", "")[
                            :8
                        ]
                        side_short_retry = side[:1].upper()
                        timestamp_short_retry = str(int(time.time() * 1000))[-10:]
                        uuid_short_retry = uuid.uuid4().hex[:8]
                        cl_ord_id_retry = f"{symbol_clean_retry}{side_short_retry}{timestamp_short_retry}{uuid_short_retry}"[
                            :32
                        ]

                        retry_result = await self.client.place_futures_order(
                            symbol=symbol,
                            side=side,
                            size=size,
                            price=corrected_price,
                            order_type="limit",
                            cl_ord_id=cl_ord_id_retry,  # ✅ Передаем исправленный clOrdId
                        )
                        if retry_result.get("code") == "0":
                            order_id = retry_result.get("data", [{}])[0].get("ordId")
                            logger.info(
                                f"✅ Лимитный ордер размещен с скорректированной ценой: {order_id}"
                            )
                            return {
                                "success": True,
                                "order_id": order_id,
                                "order_type": "limit",
                                "symbol": symbol,
                                "side": side,
                                "size": size,
                                "price": corrected_price,
                                "timestamp": datetime.now(),
                            }
                        else:
                            # Если скорректированная цена тоже не прошла, логируем и пробуем рыночный ордер
                            logger.warning(
                                f"⚠️ Скорректированная цена ({corrected_price:.2f}) также не прошла, "
                                f"пробуем рыночный ордер"
                            )
                    elif side.lower() == "buy" and parsed_max_buy:
                        # Для BUY: цена должна быть <= max_buy_price
                        # ✅ ИСПРАВЛЕНО: Используем 0.2% ниже лимита для большей безопасности
                        corrected_price = parsed_max_buy * 0.998  # 0.2% ниже лимита
                        # ✅ ИСПРАВЛЕНО: Всегда пробуем скорректированную цену, даже если она выше старой
                        # Проблема была в том, что старая цена была неправильной (выше лимита)
                        logger.info(
                            f"🔄 Пробуем скорректированную цену для {symbol} BUY: {price:.2f} → {corrected_price:.2f} "
                            f"(max_buy={parsed_max_buy:.2f}, offset=0.2%)"
                        )
                        # Пробуем разместить ордер с скорректированной ценой
                        # ✅ Генерируем уникальный clOrdId для retry
                        symbol_clean_retry = symbol.replace("-", "").replace("_", "")[
                            :8
                        ]
                        side_short_retry = side[:1].upper()
                        timestamp_short_retry = str(int(time.time() * 1000))[-10:]
                        uuid_short_retry = uuid.uuid4().hex[:8]
                        cl_ord_id_retry = f"{symbol_clean_retry}{side_short_retry}{timestamp_short_retry}{uuid_short_retry}"[
                            :32
                        ]

                        retry_result = await self.client.place_futures_order(
                            symbol=symbol,
                            side=side,
                            size=size,
                            price=corrected_price,
                            order_type="limit",
                            cl_ord_id=cl_ord_id_retry,  # ✅ Передаем исправленный clOrdId
                        )
                        if retry_result.get("code") == "0":
                            order_id = retry_result.get("data", [{}])[0].get("ordId")
                            logger.info(
                                f"✅ Лимитный ордер размещен с скорректированной ценой: {order_id}"
                            )
                            return {
                                "success": True,
                                "order_id": order_id,
                                "order_type": "limit",
                                "symbol": symbol,
                                "side": side,
                                "size": size,
                                "price": corrected_price,
                                "timestamp": datetime.now(),
                            }
                        else:
                            # Если скорректированная цена тоже не прошла, логируем и пробуем рыночный ордер
                            logger.warning(
                                f"⚠️ Скорректированная цена ({corrected_price:.2f}) также не прошла, "
                                f"пробуем рыночный ордер"
                            )

                    # ✅ Fallback: Если не удалось скорректировать цену, используем рыночный ордер
                    logger.warning(
                        f"⚠️ Не удалось скорректировать цену, пробуем рыночный ордер как fallback"
                    )
                    market_result = await self._place_market_order(symbol, side, size)
                    if market_result.get("success"):
                        logger.info(
                            f"✅ Рыночный ордер размещен как fallback (лимитный был отклонен)"
                        )
                    return market_result

                logger.error(
                    f"❌ Ошибка размещения лимитного ордера: {error_msg} (code: {error_code})"
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "order_type": "limit",
                    "error_code": error_code,
                }

        except Exception as e:
            logger.error(f"Ошибка размещения лимитного ордера: {e}")
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: При исключении тоже пробуем рыночный ордер
            try:
                logger.warning(
                    f"⚠️ Исключение при размещении лимитного ордера, пробуем рыночный как fallback"
                )
                market_result = await self._place_market_order(symbol, side, size)
                if market_result.get("success"):
                    logger.info(
                        f"✅ Рыночный ордер размещен как fallback (исключение при лимитном)"
                    )
                return market_result
            except Exception as market_error:
                logger.error(
                    f"❌ Ошибка размещения рыночного ордера (fallback): {market_error}"
                )
                return {"success": False, "error": str(e)}

    async def _place_oco_order(
        self, signal: Dict[str, Any], size: float
    ) -> Dict[str, Any]:
        """Размещение OCO ордера"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")

            # Расчет цен TP и SL
            tp_price, sl_price = await self._calculate_tp_sl_prices(signal, size)

            logger.info(
                f"🎯 Размещение OCO ордера: {symbol} {side} {size:.6f} TP:{tp_price:.2f} SL:{sl_price:.2f}"
            )

            result = await self.client.place_oco_order(
                symbol=symbol,
                side=side,
                size=size,
                tp_price=tp_price,
                sl_price=sl_price,
            )

            if result.get("code") == "0":
                order_id = result.get("data", [{}])[0].get("ordId")
                logger.info(f"✅ OCO ордер размещен: {order_id}")

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_type": "oco",
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "timestamp": datetime.now(),
                }
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка размещения OCO ордера: {error_msg}")

                return {"success": False, "error": error_msg, "order_type": "oco"}

        except Exception as e:
            logger.error(f"Ошибка размещения OCO ордера: {e}")
            return {"success": False, "error": str(e)}

    async def _calculate_tp_sl_prices(
        self, signal: Dict[str, Any], size: float
    ) -> Tuple[float, float]:
        """
        🎯 РАСЧЕТ ПЛАВАЮЩИХ TP/SL

        Адаптивные TP/SL на основе:
        - Режима рынка (trending/ranging/choppy)
        - Волатильности (ATR)
        - Силы сигнала
        """
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            entry_price = signal.get("price", 0.0)

            # ✅ ИСПРАВЛЕНИЕ: Если цена не указана, получаем текущую цену
            if entry_price == 0.0:
                try:
                    import aiohttp

                    inst_id = f"{symbol}-SWAP"
                    url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get("code") == "0" and data.get("data"):
                                    ticker = data["data"][0]
                                    entry_price = float(ticker.get("last", "0"))
                except Exception as e:
                    logger.error(f"❌ Не удалось получить цену для {symbol}: {e}")
                    # Fallback
                    if "BTC" in symbol:
                        entry_price = 110000.0
                    elif "ETH" in symbol:
                        entry_price = 3900.0
                    else:
                        entry_price = 50000.0

            if entry_price == 0.0:
                logger.error(f"❌ Цена для {symbol} = 0, невозможно рассчитать TP/SL")
                return entry_price * 1.003, entry_price * 0.998  # Fallback

            # Получаем ATR для текущей волатильности
            atr = await self._get_current_atr(symbol, entry_price)

            # ✅ НОВОЕ: Логирование высокой волатильности (>5% за период)
            atr_percent = (atr / entry_price) * 100 if entry_price > 0 else 0
            if atr_percent > 5.0:  # > 5% волатильность
                logger.warning(
                    f"⚠️ Высокая волатильность для {symbol}: "
                    f"ATR={atr_percent:.2f}%, entry_price={entry_price:.2f}, "
                    f"ATR_abs={atr:.2f}"
                )

            # Получаем режим рынка (если доступен)
            regime = signal.get("regime", "ranging")
            regime_params = self._get_regime_params(regime)

            # 🎯 АДАПТИВНЫЕ МУЛЬТИПЛИКАТОРЫ
            if regime_params:
                tp_multiplier = regime_params.get("tp_atr_multiplier", 0.6)
                sl_multiplier = regime_params.get("sl_atr_multiplier", 0.4)
            else:
                # Fallback на конфигурацию
                tp_multiplier = float(self.scalping_config.get("tp_percent", 0.3))
                sl_multiplier = float(self.scalping_config.get("sl_percent", 0.2))

            # ✅ ОБРАБОТКА КОНФЛИКТА RSI/EMA: Ужесточаем TP/SL для быстрого скальпа
            has_conflict = signal.get("has_conflict", False)
            if has_conflict:
                # При конфликте: более агрессивный TP и узкий SL для быстрого выхода
                # TP: 0.25-0.3 ATR (быстрая прибыль на коррекции)
                # SL: 0.2-0.25 ATR (быстрый выход при ошибке)
                tp_multiplier = min(
                    tp_multiplier * 0.5, 0.3
                )  # Макс 0.3 ATR для быстрого скальпа
                sl_multiplier = min(
                    sl_multiplier * 0.5, 0.25
                )  # Макс 0.25 ATR для узкого SL
                logger.debug(
                    f"⚡ Конфликт RSI/EMA: адаптированные TP/SL для быстрого скальпа "
                    f"(TP={tp_multiplier:.2f}x ATR, SL={sl_multiplier:.2f}x ATR)"
                )

            # Адаптация под силу сигнала
            strength = signal.get("strength", 0.5)
            # Если конфликт, не увеличиваем multiplier от strength (уже достаточно агрессивный)
            if not has_conflict:
                tp_multiplier *= 0.5 + strength  # 0.5x-1.5x range
                sl_multiplier *= 0.5 + strength

            # 🎯 РАСЧЕТ ОТ ATR (ПЛАВАЮЩИЙ!)
            tp_distance = atr * tp_multiplier
            sl_distance = atr * sl_multiplier

            # ✅ FALLBACK: если ATR-based SL слишком мал → использовать sl_percent
            # Получаем sl_percent из regime_params или из глобального конфига
            sl_percent_value = None
            if regime_params:
                sl_percent_value = regime_params.get("sl_percent")
                if sl_percent_value is not None:
                    logger.info(
                        f"✅ Используется адаптивный sl_percent={sl_percent_value:.2f}% для {symbol} "
                        f"(regime={regime})"
                    )

            if sl_percent_value is None:
                # Fallback на глобальный sl_percent из конфига
                sl_percent_value = getattr(self.scalping_config, "sl_percent", 1.2)
                logger.warning(
                    f"⚠️ FALLBACK: Используется глобальный sl_percent={sl_percent_value:.2f}% для {symbol} "
                    f"(regime={regime}, regime_params={'пуст' if not regime_params else 'не содержит sl_percent'})"
                )

            # Рассчитываем минимальный SL в абсолютных единицах
            sl_percent_abs = entry_price * (sl_percent_value / 100.0)

            # ✅ ИСПРАВЛЕНО: Если ATR-based SL меньше минимального → используем sl_percent
            # НО: если ATR-based SL больше минимального, используем ATR-based (он более точный)
            if sl_distance < sl_percent_abs:
                old_sl_distance = sl_distance
                sl_distance = sl_percent_abs
                logger.info(
                    f"⚠️ ATR-based SL слишком мал ({old_sl_distance/entry_price*100:.2f}%) "
                    f"→ используем sl_percent fallback ({sl_percent_value:.2f}%) для {symbol} "
                    f"(regime={regime}, ATR-based={old_sl_distance/entry_price*100:.2f}% < {sl_percent_value:.2f}%)"
                )
            else:
                logger.info(
                    f"✅ Используется ATR-based SL ({sl_distance/entry_price*100:.2f}%) для {symbol} "
                    f"(regime={regime}, больше минимального {sl_percent_value:.2f}%)"
                )

            if side.lower() == "buy":
                tp_price = entry_price + tp_distance
                sl_price = entry_price - sl_distance
            else:  # sell
                tp_price = entry_price - tp_distance
                sl_price = entry_price + sl_distance

            logger.info(
                f"🎯 Адаптивные TP/SL для {symbol}: "
                f"regime={regime}, ATR={atr:.2f}, "
                f"TP={tp_distance/entry_price*100:.2f}%, "
                f"SL={sl_distance/entry_price*100:.2f}%, "
                f"entry={entry_price:.2f}, tp_price={tp_price:.2f}, sl_price={sl_price:.2f}"
            )

            return tp_price, sl_price

        except Exception as e:
            logger.error(f"Ошибка расчета TP/SL цен: {e}")
            # Fallback на фиксированные %
            entry_price = signal.get("price", 0.0)
            if entry_price == 0.0:
                # Если цена не указана, используем текущую цену
                try:
                    import aiohttp

                    inst_id = f"{symbol}-SWAP"
                    url = f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get("code") == "0" and data.get("data"):
                                    ticker = data["data"][0]
                                    entry_price = float(ticker.get("last", "0"))
                except Exception:
                    logger.error(f"❌ Fallback: не удалось получить цену для {symbol}")
                    # Последний fallback - используем разумное значение на основе символа
                    if "BTC" in symbol:
                        entry_price = 110000.0
                    elif "ETH" in symbol:
                        entry_price = 3900.0
                    else:
                        entry_price = 50000.0
            tp_pct = self.scalping_config.tp_percent
            sl_pct = self.scalping_config.sl_percent

            side = signal.get("side", "buy")
            if side.lower() == "buy":
                return entry_price * (1 + tp_pct / 100), entry_price * (
                    1 - sl_pct / 100
                )
            else:
                return entry_price * (1 - tp_pct / 100), entry_price * (
                    1 + sl_pct / 100
                )

    async def _get_current_atr(self, symbol: str, price: float) -> float:
        """Получает текущий ATR для инструмента"""
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем РЕАЛЬНЫЙ ATR из исторических данных
            # Рассчитываем ATR на основе последних свечей
            import aiohttp

            # Получаем последние 14 свечей (для расчета ATR period=14)
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем 5m вместо 1m для более стабильного ATR
            inst_id = f"{symbol}-SWAP"
            url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=5m&limit=20"

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == "0" and data.get("data"):
                            candles = data["data"]

                            if (
                                len(candles) >= 15
                            ):  # Нужно минимум 15 свечей для ATR(14)
                                # OKX формат: [timestamp, open, high, low, close, volume, volumeCcy]
                                true_ranges = []
                                for i in range(
                                    1, min(15, len(candles))
                                ):  # Используем последние 14
                                    high = float(candles[i][2])
                                    low = float(candles[i][3])
                                    prev_close = float(candles[i - 1][4])

                                    tr = max(
                                        high - low,
                                        abs(high - prev_close),
                                        abs(low - prev_close),
                                    )
                                    true_ranges.append(tr)

                                # ATR = среднее значение True Range за период
                                if true_ranges:
                                    atr = sum(true_ranges) / len(true_ranges)
                                    logger.debug(
                                        f"📊 ATR для {symbol}: {atr:.2f} (на основе {len(true_ranges)} свечей)"
                                    )
                                    return atr

            # Fallback: используем приблизительный ATR как 1% от цены
            fallback_atr = price * 0.01
            logger.warning(
                f"⚠️ Не удалось рассчитать ATR для {symbol}, используем fallback: {fallback_atr:.2f}"
            )
            return fallback_atr

        except Exception as e:
            logger.warning(f"Ошибка получения ATR: {e}")
            return price * 0.01  # 1% по умолчанию

    def _get_regime_params(self, regime: str) -> dict:
        """Получает параметры режима из ARM"""
        try:
            # ✅ ИСПРАВЛЕНО: Если есть доступ к оркестратору - используем его метод
            if hasattr(self, "orchestrator") and self.orchestrator:
                return self.orchestrator._get_regime_params(regime)

            # ✅ ИСПРАВЛЕНО: Правильный путь к конфигу через scalping_config
            if not hasattr(self, "scalping_config") or not self.scalping_config:
                logger.warning("⚠️ scalping_config не найден в OrderExecutor")
                return {}

            # Получаем adaptive_regime из scalping_config
            adaptive_regime = None
            if hasattr(self.scalping_config, "adaptive_regime"):
                adaptive_regime = getattr(self.scalping_config, "adaptive_regime", None)
            elif isinstance(self.scalping_config, dict):
                adaptive_regime = self.scalping_config.get("adaptive_regime", {})

            if not adaptive_regime:
                logger.warning(
                    f"⚠️ adaptive_regime не найден в scalping_config для режима {regime}"
                )
                return {}

            # Преобразуем в dict если нужно
            if not isinstance(adaptive_regime, dict):
                if hasattr(adaptive_regime, "dict"):
                    adaptive_regime = adaptive_regime.dict()
                elif hasattr(adaptive_regime, "model_dump"):
                    adaptive_regime = adaptive_regime.model_dump()
                elif hasattr(adaptive_regime, "__dict__"):
                    adaptive_regime = dict(adaptive_regime.__dict__)
                else:
                    adaptive_regime = {}

            regime_params = adaptive_regime.get(regime.lower(), {})

            # Преобразуем regime_params в dict если нужно
            if regime_params and not isinstance(regime_params, dict):
                if hasattr(regime_params, "dict"):
                    regime_params = regime_params.dict()
                elif hasattr(regime_params, "model_dump"):
                    regime_params = regime_params.model_dump()
                elif hasattr(regime_params, "__dict__"):
                    regime_params = dict(regime_params.__dict__)
                else:
                    regime_params = {}

            if not regime_params:
                logger.warning(
                    f"⚠️ Параметры режима {regime} не найдены в adaptive_regime"
                )

            return regime_params
        except Exception as e:
            logger.error(
                f"❌ Ошибка получения параметров режима {regime}: {e}", exc_info=True
            )
            return {}

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Отмена ордера"""
        try:
            logger.info(f"🛑 Отмена ордера: {order_id} ({symbol})")

            result = await self.client.cancel_order(symbol, order_id)

            if result.get("code") == "0":
                logger.info(f"✅ Ордер {order_id} отменен")

                # Удаление из активных ордеров
                if order_id in self.active_orders:
                    del self.active_orders[order_id]

                return {"success": True, "order_id": order_id}
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка отмены ордера: {error_msg}")

                return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error(f"Ошибка отмены ордера: {e}")
            return {"success": False, "error": str(e)}

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Отмена всех ордеров"""
        try:
            cancelled_count = 0
            errors = []

            # Получение активных ордеров
            orders_to_cancel = []
            for order_id, order_info in self.active_orders.items():
                if symbol is None or order_info["symbol"] == symbol:
                    orders_to_cancel.append((order_id, order_info["symbol"]))

            # Отмена ордеров
            for order_id, order_symbol in orders_to_cancel:
                result = await self.cancel_order(order_id, order_symbol)
                if result.get("success"):
                    cancelled_count += 1
                else:
                    errors.append(f"{order_id}: {result.get('error')}")

            logger.info(f"✅ Отменено ордеров: {cancelled_count}")
            # ✅ Обновляем метрики отменённых ордеров
            try:
                self.execution_stats["cancelled_orders"] += cancelled_count
            except Exception:
                pass

            return {
                "success": True,
                "cancelled_count": cancelled_count,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Ошибка отмены всех ордеров: {e}")
            return {"success": False, "error": str(e)}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Получение статуса ордера"""
        try:
            # Здесь нужно интегрироваться с API для получения статуса ордера
            # Пока используем заглушку

            if order_id in self.active_orders:
                order_info = self.active_orders[order_id]
                return {
                    "order_id": order_id,
                    "status": "active",
                    "symbol": order_info["symbol"],
                    "side": order_info["side"],
                    "size": order_info["size"],
                    "type": order_info["type"],
                    "timestamp": order_info["timestamp"],
                }
            else:
                return {"order_id": order_id, "status": "not_found"}

        except Exception as e:
            logger.error(f"Ошибка получения статуса ордера: {e}")
            return {"error": str(e)}

    def _update_execution_stats(self, result: Dict[str, Any]):
        """Обновление статистики исполнения"""
        try:
            self.execution_stats["total_orders"] += 1

            if result.get("success"):
                self.execution_stats["successful_orders"] += 1
            else:
                self.execution_stats["failed_orders"] += 1

            # Сохранение в историю
            self.order_history.append({"timestamp": datetime.now(), "result": result})

            # Ограничение истории последними 1000 записями
            if len(self.order_history) > 1000:
                self.order_history = self.order_history[-1000:]

        except Exception as e:
            logger.error(f"Ошибка обновления статистики: {e}")

    def get_execution_statistics(self) -> Dict[str, Any]:
        """Получение статистики исполнения"""
        try:
            total = self.execution_stats["total_orders"]
            successful = self.execution_stats["successful_orders"]
            failed = self.execution_stats["failed_orders"]
            cancelled = self.execution_stats.get("cancelled_orders", 0)

            success_rate = (successful / total * 100) if total > 0 else 0

            return {
                "total_orders": total,
                "successful_orders": successful,
                "failed_orders": failed,
                "cancelled_orders": cancelled,
                "cancel_ratio": (cancelled / total * 100) if total > 0 else 0.0,
                "success_rate": success_rate,
                "active_orders_count": len(self.active_orders),
                "last_order_time": self.order_history[-1]["timestamp"]
                if self.order_history
                else None,
                # Доп. метрики
                "market_orders": self.execution_stats.get("market_orders", 0),
                "limit_orders_maker": self.execution_stats.get("limit_orders_maker", 0),
                "limit_orders_other": self.execution_stats.get("limit_orders_other", 0),
                "avg_slippage_bps": (
                    self.execution_stats["total_slippage_bps"]
                    / self.execution_stats["slippage_samples"]
                    if self.execution_stats.get("slippage_samples", 0) > 0
                    else 0.0
                ),
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики исполнения: {e}")
            return {"error": str(e)}


# Пример использования
if __name__ == "__main__":
    # Создаем конфигурацию
    config = BotConfig(
        api_key="test_key",
        secret_key="test_secret",
        passphrase="test_passphrase",
        sandbox=True,
    )

    # Создаем клиент и slippage guard
    client = OKXFuturesClient("test_key", "test_secret", "test_passphrase")
    slippage_guard = SlippageGuard()

    # Создаем исполнитель ордеров
    executor = FuturesOrderExecutor(config, client, slippage_guard)

    print("FuturesOrderExecutor готов к работе")
