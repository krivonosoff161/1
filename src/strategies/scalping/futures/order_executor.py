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
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig, ScalpingConfig
from src.strategies.modules.slippage_guard import SlippageGuard

from .config.config_view import get_scalping_view


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
        self.scalping_config = get_scalping_view(config)
        self.client = client
        self.slippage_guard = slippage_guard
        self.performance_tracker = None  # Будет установлен из orchestrator
        self.data_registry = None  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): DataRegistry для получения волатильности
        self.signal_generator = None  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): SignalGenerator для получения волатильности
        self.telegram = None  # TelegramNotifier — устанавливается из orchestrator

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

    def set_telegram(self, telegram):
        """Установить TelegramNotifier для отправки сигнальных уведомлений"""
        self.telegram = telegram
        logger.debug("✅ FuturesOrderExecutor: TelegramNotifier установлен")

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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (24.01.2026): Сохраняем цену сигнала для проверки в _place_market_order
            if not hasattr(self, "_last_signal_price"):
                self._last_signal_price = {}
            signal_price = signal.get("price") or signal.get("entry_price")
            if signal_price:
                self._last_signal_price[symbol] = float(signal_price)

            # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ: Логируем информацию о сигнале
            logger.debug(
                f"🔍 [EXECUTE_SIGNAL] {symbol} {side}: "
                f"size={position_size:.6f}, signal_type={signal.get('type', 'limit')}, "
                f"regime={signal.get('regime', 'N/A')}, strength={signal.get('strength', 0):.2f}"
            )

            # Валидация сигнала через Slippage Guard
            # Require fresh WS price before opening new positions
            require_ws_fresh = True
            ws_max_age = None
            oe_cfg = None
            try:
                if isinstance(self.scalping_config, dict):
                    oe_cfg = self.scalping_config.get("order_executor", {})
                else:
                    oe_cfg = getattr(self.scalping_config, "order_executor", {})
                if isinstance(oe_cfg, dict):
                    if "ws_fresh_max_age" in oe_cfg:
                        ws_max_age = float(oe_cfg.get("ws_fresh_max_age"))
                else:
                    if hasattr(oe_cfg, "ws_fresh_max_age"):
                        ws_max_age = float(getattr(oe_cfg, "ws_fresh_max_age"))
            except Exception:
                pass
            # Если ws_fresh_max_age не задан, используем TTL из DataRegistry (обычно = signal_generator.ws_fresh_max_age)
            try:
                if (
                    self.data_registry
                    and hasattr(self.data_registry, "market_data_ttl")
                    and ws_max_age is None
                ):
                    ws_max_age = float(self.data_registry.market_data_ttl)
            except Exception:
                pass
            if ws_max_age is None:
                ws_max_age = 1.5
            if (
                require_ws_fresh
                and self.data_registry
                and hasattr(self.data_registry, "is_ws_fresh")
            ):
                try:
                    if not await self.data_registry.is_ws_fresh(
                        symbol, max_age=ws_max_age
                    ):
                        logger.warning(
                            f"WS_STALE_ORDER_BLOCK {symbol}: no fresh WS price within {ws_max_age:.1f}s, skip entry"
                        )
                        return {
                            "success": False,
                            "error": "WS stale, entry blocked",
                        }
                except Exception as e:
                    logger.debug(
                        f"OrderExecutor WS freshness check error for {symbol}: {e}"
                    )

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

            # ✅ ИСПРАВЛЕНО ПРОБЛЕМА #4: Проверка дельты цены ПЕРЕД размещением ордера
            # Получаем текущую цену для проверки дельты
            current_price_for_check = 0.0
            signal_price = signal.get("price", 0.0) if signal else 0.0

            # ✅ КРИТИЧНО (09.01.2026): Используем DataRegistry WebSocket вместо REST API!
            try:
                if hasattr(self, "data_registry") and self.data_registry:
                    snapshot = await self.data_registry.get_decision_price_snapshot(
                        symbol=symbol,
                        client=self.client,
                        max_age=3.0,
                        allow_rest_fallback=True,
                    )
                    if snapshot:
                        snap_price = float(snapshot.get("price") or 0.0)
                        if snap_price > 0:
                            current_price_for_check = snap_price
                            snap_source = snapshot.get("source", "UNKNOWN")
                            snap_age = snapshot.get("age")
                            age_str = (
                                f"{float(snap_age):.1f}s"
                                if isinstance(snap_age, (int, float))
                                else "N/A"
                            )
                            logger.debug(
                                f"✅ OrderExecutor: decision snapshot for delta check {symbol}: "
                                f"price={current_price_for_check:.2f}, source={snap_source}, age={age_str}"
                            )
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось получить текущую цену для проверки дельты: {e}"
                )

            # Проверяем дельту между ценой сигнала и текущей ценой
            price_delta_pct = 0.0
            if current_price_for_check > 0 and signal_price > 0:
                price_delta_pct = (
                    abs(signal_price - current_price_for_check)
                    / current_price_for_check
                    * 100
                )

            # ✅ Если дельта > 1% - используем market ордер для быстрого исполнения
            if price_delta_pct > 1.0:
                logger.warning(
                    f"⚠️ ПРОБЛЕМА #4: Большая дельта цены для {symbol}: {price_delta_pct:.2f}% "
                    f"(signal_price={signal_price:.2f}, current_price={current_price_for_check:.2f}), "
                    f"используем market ордер для быстрого исполнения"
                )
                order_type = "market"
            elif price_delta_pct > 0.5:
                logger.info(
                    f"💰 Дельта цены для {symbol}: {price_delta_pct:.2f}% "
                    f"(signal_price={signal_price:.2f}, current_price={current_price_for_check:.2f}), "
                    f"используем limit ордер с уменьшенным offset"
                )

            # Расчет цены для лимитных ордеров
            price = None
            if order_type == "limit":
                regime = signal.get("regime", None)
                price = await self._calculate_limit_price(
                    symbol, side, regime=regime, signal=signal
                )
                # Если не удалось рассчитать цену или цена устарела — fallback на market
                if price is None or price <= 0:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (24.01.2026): Проверка возраста сигнала
                    # Если данные устарели, проверяем возраст сигнала перед fallback на market
                    signal_timestamp = signal.get("timestamp")
                    if signal_timestamp:
                        try:
                            if isinstance(signal_timestamp, str):
                                signal_dt = datetime.fromisoformat(
                                    signal_timestamp.replace("Z", "+00:00")
                                )
                            elif isinstance(signal_timestamp, datetime):
                                signal_dt = signal_timestamp
                            else:
                                signal_dt = datetime.fromtimestamp(
                                    float(signal_timestamp), tz=timezone.utc
                                )

                            signal_age_sec = (
                                datetime.now(timezone.utc)
                                - signal_dt.astimezone(timezone.utc)
                            ).total_seconds()

                            if signal_age_sec > 10.0:  # Сигнал старше 10 секунд
                                logger.error(
                                    f"❌ ЗАЩИТА: {symbol} сигнал устарел на {signal_age_sec:.1f}s (>10s), "
                                    f"лимитная цена не рассчитана - ОТМЕНЯЕМ ордер полностью!"
                                )
                                return {
                                    "success": False,
                                    "error": f"Signal too old: {signal_age_sec:.1f}s",
                                    "code": "STALE_SIGNAL",
                                }
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Не удалось проверить возраст сигнала для {symbol}: {e}"
                            )

                    logger.error(
                        f"❌ Лимитный ордер для {symbol} не размещён: нет свежей цены или ошибка расчёта. Fallback на market."
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

                # FIX 2026-02-22 P1: Telegram уведомление для market/limit ордеров
                # OCO уже уведомляет внутри _place_oco_order — не дублируем
                if self.telegram and order_type in ("market", "limit"):
                    try:
                        # FIX 2026-02-25: правильный приоритет цены для уведомления.
                        # Раньше signal.get("price") был первым — это стале цена DataRegistry.
                        # Теперь: fill_price (avgPx из OKX) > est_entry (best_ask/bid) >
                        # current_price_for_check (live snapshot) > signal price (last resort).
                        entry_for_telegram = float(
                            result.get("fill_price")  # avgPx из OKX (market ордер)
                            or result.get(
                                "est_entry"
                            )  # best_ask/bid в момент размещения
                            or current_price_for_check  # live snapshot (3s max-age + REST)
                            or signal.get(
                                "price", 0.0
                            )  # стале сигнальная цена (last resort)
                            or signal.get("entry_price", 0.0)
                            or 0.0
                        )
                        (
                            approx_tp_price,
                            approx_sl_price,
                        ) = self._estimate_tp_sl_for_telegram(
                            signal=signal, entry_price=entry_for_telegram
                        )
                        _size_usd = (
                            position_size * entry_for_telegram
                            if entry_for_telegram > 0
                            else 0.0
                        )
                        asyncio.create_task(
                            self.telegram.send_trade_open(
                                signal=signal,
                                tp_price=approx_tp_price,
                                sl_price=approx_sl_price,
                                size_usd=_size_usd,
                                entry_price=entry_for_telegram,
                            )
                        )
                    except Exception as _tg_err:
                        logger.debug(f"Telegram send_trade_open error: {_tg_err}")

            return result

        except Exception as e:
            logger.error(f"Ошибка исполнения ордера: {e}")
            logger.error(f"[TRACE] _execute_order stack:\n{traceback.format_exc()}")
            try:
                logger.error(
                    f"[TRACE] _execute_order locals keys: {list(locals().keys())}"
                )
            except Exception:
                pass
            return {"success": False, "error": str(e)}

    def _get_adaptive_regime_baseline_tp_sl(self, regime: str) -> Tuple[float, float]:
        """Базовые TP/SL проценты из adaptive_regime[regime] для Telegram."""
        regime_key = str(regime or "ranging").lower()

        def _to_dict(obj: Any) -> Dict[str, Any]:
            if obj is None:
                return {}
            if isinstance(obj, dict):
                return obj
            if hasattr(obj, "model_dump"):
                dumped = obj.model_dump()
                return dumped if isinstance(dumped, dict) else {}
            if hasattr(obj, "dict"):
                dumped = obj.dict()
                return dumped if isinstance(dumped, dict) else {}
            if hasattr(obj, "__dict__"):
                return dict(obj.__dict__)
            return {}

        tp_percent = 0.0
        sl_percent = 0.0

        try:
            scalping_cfg = self.scalping_config
            adaptive_regime_cfg = (
                scalping_cfg.get("adaptive_regime", {})
                if isinstance(scalping_cfg, dict)
                else getattr(scalping_cfg, "adaptive_regime", {})
            )
            adaptive_regime_dict = _to_dict(adaptive_regime_cfg)
            regime_cfg = _to_dict(adaptive_regime_dict.get(regime_key, {}))

            tp_percent = float(regime_cfg.get("tp_percent", 0) or 0)
            sl_percent = float(regime_cfg.get("sl_percent", 0) or 0)

            if tp_percent <= 0:
                tp_percent = float(
                    (
                        scalping_cfg.get("tp_percent", 0)
                        if isinstance(scalping_cfg, dict)
                        else getattr(scalping_cfg, "tp_percent", 0)
                    )
                    or 0
                )
            if sl_percent <= 0:
                sl_percent = float(
                    (
                        scalping_cfg.get("sl_percent", 0)
                        if isinstance(scalping_cfg, dict)
                        else getattr(scalping_cfg, "sl_percent", 0)
                    )
                    or 0
                )
        except Exception as exc:
            logger.debug(
                f"⚠️ OrderExecutor: failed to read baseline TP/SL for regime={regime_key}: {exc}"
            )

        return max(tp_percent, 0.0), max(sl_percent, 0.0)

    def _estimate_tp_sl_for_telegram(
        self, signal: Dict[str, Any], entry_price: float
    ) -> Tuple[Optional[float], Optional[float]]:
        """Ориентировочные TP/SL цены для уведомления Telegram."""
        if entry_price <= 0:
            return None, None

        side = str(signal.get("side", "buy")).lower()
        regime = str(signal.get("regime", "ranging")).lower()
        tp_percent, sl_percent = self._get_adaptive_regime_baseline_tp_sl(regime)
        if tp_percent <= 0 or sl_percent <= 0:
            return None, None

        if side in ("buy", "long"):
            tp_price = entry_price * (1 + tp_percent / 100.0)
            sl_price = entry_price * (1 - sl_percent / 100.0)
        else:
            tp_price = entry_price * (1 - tp_percent / 100.0)
            sl_price = entry_price * (1 + sl_percent / 100.0)

        return tp_price, sl_price

    def _determine_order_type(self, signal: Dict[str, Any]) -> str:
        """Определение типа ордера на основе сигнала"""
        # ✅ Приоритет: если в конфиге включены market-входы — используем market
        try:
            order_executor_cfg = getattr(self.scalping_config, "order_executor", {})
            limit_cfg = (
                order_executor_cfg.get("limit_order", {}) if order_executor_cfg else {}
            )
            use_market = False
            if isinstance(limit_cfg, dict):
                use_market = bool(limit_cfg.get("use_market_order", False))
                regime = signal.get("regime")
                if regime and isinstance(limit_cfg.get("by_regime"), dict):
                    regime_cfg = limit_cfg["by_regime"].get(str(regime).lower(), {})
                    if (
                        isinstance(regime_cfg, dict)
                        and regime_cfg.get("use_market_order") is True
                    ):
                        use_market = True
            if use_market:
                return "market"
        except Exception:
            pass
        # ✅ ИСПРАВЛЕНО (04.01.2026): Используем limit ордера для экономии комиссий
        # Market ордера имеют комиссию 0.05% (taker), limit ордера - 0.02% (maker)
        # Экономия: $108/месяц при 200 сделках/день
        signal_type = signal.get(
            "type", "limit"
        )  # ✅ ИСПРАВЛЕНО: "limit" вместо "market" для экономии комиссий

        # Если signal_type это тип ордера (market, limit, oco) - используем его
        if signal_type in ["market", "limit", "oco"]:
            return signal_type

        # ✅ ИСПРАВЛЕНО: Используем limit по умолчанию для экономии комиссий
        return "limit"  # ✅ ИСПРАВЛЕНО: "limit" вместо "market"

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
            # ✅ Проверка актуальности локальной цены из DataRegistry (TTL 0.5s)
            md_age_sec = None
            if getattr(self, "data_registry", None):
                try:
                    md = await self.data_registry.get_market_data(symbol)
                    if md:
                        # Предпочитаем timestamp из current_tick, если он есть
                        md_ts = None
                        current_tick = None
                        if isinstance(md, dict):
                            current_tick = md.get("current_tick")
                            updated_at = md.get("updated_at")
                            if md_ts is None and hasattr(current_tick, "timestamp"):
                                md_ts = current_tick.timestamp
                            if md_ts is None and isinstance(updated_at, datetime):
                                md_ts = updated_at.timestamp()
                        else:
                            # Объект с атрибутами
                            current_tick = getattr(md, "current_tick", None)
                            updated_at = getattr(md, "updated_at", None)
                            if md_ts is None and hasattr(current_tick, "timestamp"):
                                md_ts = current_tick.timestamp
                            if md_ts is None and isinstance(updated_at, datetime):
                                md_ts = updated_at.timestamp()

                        if md_ts:
                            md_age_sec = time.time() - md_ts
                            if md_age_sec is not None and md_age_sec > 1.0:
                                logger.warning(
                                    f"⚠️ DataRegistry price for {symbol} устарела на {md_age_sec:.3f}s (>1.0s), "
                                    f"пытаемся получить свежую цену через REST API..."
                                )
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (25.01.2026): REST fallback вместо отказа
                                try:
                                    fresh_price = await self.data_registry.get_fresh_price_for_orders(
                                        symbol, client=self.client
                                    )
                                    if fresh_price and fresh_price > 0:
                                        logger.info(
                                            f"✅ OrderExecutor: Получена свежая цена для {symbol}: ${fresh_price:.4f}, "
                                            f"продолжаем расчет лимитной цены"
                                        )
                                        # Обновляем md_age_sec на 0 т.к. получили свежие данные
                                        md_age_sec = 0.0
                                    else:
                                        logger.error(
                                            f"❌ OrderExecutor: REST fallback failed для {symbol}, "
                                            f"fallback на market order"
                                        )
                                        return None  # Fallback на market
                                except Exception as e:
                                    logger.error(
                                        f"❌ OrderExecutor: Ошибка REST fallback для {symbol}: {e}, "
                                        f"fallback на market order"
                                    )
                                    return None  # Fallback на market
                        else:
                            # ✅ FIX (22.01.2026): Если нет timestamp, данные могут быть устаревшими
                            logger.warning(
                                f"⚠️ Нет timestamp для DataRegistry {symbol}, возможно данные устаревшие. Fallback на market."
                            )
                            return None
                    else:
                        # ✅ FIX (22.01.2026): Если нет market_data, не размещаем лимитку
                        logger.warning(
                            f"⚠️ Нет market_data для {symbol}, fallback на market."
                        )
                        return None
                except Exception as e:
                    # ✅ FIX (22.01.2026): Если ошибка связана с устаревшими данными, возвращаем None
                    error_msg = str(e).lower()
                    if (
                        "stale" in error_msg
                        or "устар" in error_msg
                        or "нет актуальных" in error_msg
                    ):
                        logger.error(
                            f"❌ DataRegistry для {symbol} вернул ошибку о устаревших данных: {e} — fallback на market"
                        )
                        return None
                    logger.debug(
                        f"⚠️ Не удалось проверить свежесть DataRegistry для {symbol}: {e}"
                    )

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
                    f"Лимитный ордер не будет размещён, fallback на market"
                )
                return None

            # === ДИНАМИЧЕСКАЯ АДАПТАЦИЯ OFFSET НА ОСНОВЕ ВОЛАТИЛЬНОСТИ ===
            # Если волатильность доступна — корректируем offset_percent
            try:
                volatility = None
                if self.data_registry:
                    try:
                        atr = await self.data_registry.get_indicator(symbol, "atr")
                        # Берём текущую цену из DataRegistry, если доступна
                        current_price = None
                        if hasattr(self, "data_registry"):
                            md = await self.data_registry.get_market_data(symbol)
                            if md:
                                if isinstance(md, dict):
                                    current_price = md.get("current_price")
                                else:
                                    current_price = getattr(md, "current_price", None)
                        if atr and current_price:
                            volatility = (atr / current_price) * 100.0
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить ATR для расчёта волатильности: {e}"
                        )
                # Альтернатива: regime_manager
                if volatility is None and self.signal_generator:
                    try:
                        regime_manager = (
                            self.signal_generator.regime_managers.get(symbol)
                            if hasattr(self.signal_generator, "regime_managers")
                            and self.signal_generator.regime_managers
                            else None
                        ) or getattr(self.signal_generator, "regime_manager", None)
                        if regime_manager and hasattr(
                            regime_manager, "last_volatility"
                        ):
                            volatility = regime_manager.last_volatility
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить волатильность из regime_manager: {e}"
                        )
                # === Адаптация offset ===
                if volatility is not None and volatility > 0:
                    orig_offset = offset_percent
                    # ✅ FIX (22.01.2026): Исправлена логика offset - теперь ГАРАНТИРУЕМ минимум, а не снижаем
                    # Пороговые значения можно вынести в конфиг при необходимости
                    if volatility < 0.1:
                        # Сверхнизкая волатильность — offset минимум 0.02% (было 0.005%)
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: используем max вместо min!
                        offset_percent = max(offset_percent, 0.02)
                        logger.info(
                            f"💡 Волатильность {volatility:.3f}% < 0.1% — offset установлен минимум {offset_percent:.4f}% для гарантии исполнения"
                        )
                    elif volatility < 0.3:
                        # Низкая волатильность — offset минимум 0.03% (было 0.01%)
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: используем max вместо min!
                        offset_percent = max(offset_percent, 0.03)
                        logger.info(
                            f"💡 Волатильность {volatility:.3f}% < 0.3% — offset установлен минимум {offset_percent:.4f}% для гарантии исполнения"
                        )
                    elif volatility > 0.7:
                        # Высокая волатильность — offset увеличиваем для гарантии исполнения
                        offset_percent = max(
                            offset_percent, 0.05
                        )  # Было 0.03%, стало 0.05%
                        logger.info(
                            f"💡 Волатильность {volatility:.3f}% > 0.7% — offset увеличен до {offset_percent:.4f}% для гарантии исполнения"
                        )
                    else:
                        # Средняя волатильность (0.3-0.7%) — offset минимум 0.04%
                        offset_percent = max(offset_percent, 0.04)
                        logger.info(
                            f"💡 Волатильность {volatility:.3f}% — offset установлен минимум {offset_percent:.4f}%"
                        )
                    logger.debug(
                        f"[DYNAMIC_OFFSET] {symbol}: volatility={volatility:.4f}%, orig_offset={orig_offset}, final_offset={offset_percent}"
                    )
            except Exception as e:
                logger.error(f"Ошибка динамической адаптации offset_percent: {e}")

            # ✅ КРИТИЧНО (09.01.2026): Получаем цены из DataRegistry WebSocket вместо REST API!
            price_limits = None
            price_limits_source = "unknown"
            best_bid = 0
            best_ask = 0
            current_price = 0
            ws_price = None
            ws_bid = None
            ws_ask = None

            # Tier 1: WebSocket real-time from DataRegistry
            try:
                # Проверка свежести данных и авто-reconnect WebSocket
                if hasattr(self, "data_registry") and self.data_registry:
                    # Авто-реинициализация DataRegistry при stale данных
                    await self.data_registry.auto_reinit(
                        symbol, fetch_market_data_callback=self._fetch_price_rest
                    )
                    # Авто-reconnect WebSocket
                    if (
                        hasattr(self, "websocket_coordinator")
                        and self.websocket_coordinator
                    ):
                        await self.websocket_coordinator.auto_reconnect()
                    market_data = await self.data_registry.get_market_data(symbol)
                    if (
                        market_data
                        and hasattr(market_data, "current_tick")
                        and market_data.current_tick
                    ):
                        if (
                            hasattr(market_data.current_tick, "price")
                            and market_data.current_tick.price > 0
                        ):
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (25.01.2026): Проверяем TTL перед использованием
                            tick_ts = (
                                getattr(market_data.current_tick, "timestamp", None)
                                or time.time()
                            )
                            tick_age = time.time() - tick_ts

                            if tick_age > 1.0:
                                logger.warning(
                                    f"⚠️ WebSocket price for {symbol} устарела на {tick_age:.1f}s (>1.0s), "
                                    f"пытаемся получить свежую цену через REST..."
                                )
                                # Пытаемся получить свежую цену через REST
                                fresh_price = (
                                    await self.data_registry.get_fresh_price_for_orders(
                                        symbol, client=self.client
                                    )
                                )
                                if fresh_price and fresh_price > 0:
                                    current_price = fresh_price
                                    best_bid = (
                                        fresh_price  # Используем price как bid/ask
                                    )
                                    best_ask = fresh_price
                                    ws_price, ws_bid, ws_ask = (
                                        current_price,
                                        best_bid,
                                        best_ask,
                                    )
                                    price_limits_source = "rest_fresh"
                                    logger.info(
                                        f"✅ OrderExecutor: Получена СВЕЖАЯ цена через REST для {symbol}: ${current_price:.4f}"
                                    )
                                    price_limits = {
                                        "current_price": current_price,
                                        "best_bid": best_bid,
                                        "best_ask": best_ask,
                                        "timestamp": time.time(),
                                    }
                                else:
                                    # REST fallback failed, пропускаем к Tier 2 (candle)
                                    logger.warning(
                                        f"⚠️ REST fallback failed для {symbol}, пробуем candle fallback"
                                    )
                            else:
                                # WebSocket цена свежая, используем ее
                                current_price = market_data.current_tick.price
                                best_bid = getattr(
                                    market_data.current_tick, "bid", current_price
                                )
                                best_ask = getattr(
                                    market_data.current_tick, "ask", current_price
                                )
                                ws_price, ws_bid, ws_ask = (
                                    current_price,
                                    best_bid,
                                    best_ask,
                                )
                                price_limits_source = "ws"
                                logger.debug(
                                    f"✅ OrderExecutor: WebSocket price for limit calc: {current_price:.2f} (bid={best_bid:.2f}, ask={best_ask:.2f})"
                                )
                                price_limits = {
                                    "current_price": current_price,
                                    "best_bid": best_bid,
                                    "best_ask": best_ask,
                                    "timestamp": tick_ts,
                                }
                    # Tier 2: Fallback на свечу если WebSocket недоступен
                    elif (
                        market_data
                        and hasattr(market_data, "ohlcv_data")
                        and market_data.ohlcv_data
                    ):
                        current_price = market_data.ohlcv_data[-1].close
                        best_bid = current_price
                        best_ask = current_price
                        price_limits_source = "candle"
                        logger.debug(
                            f"⚠️ OrderExecutor: Using candle for limit calc: {current_price:.2f}"
                        )
                        price_limits = {
                            "current_price": current_price,
                            "best_bid": best_bid,
                            "best_ask": best_ask,
                            "timestamp": time.time(),
                        }
            except Exception as e:
                logger.debug(f"⚠️ OrderExecutor: Failed to get DataRegistry price: {e}")

            # Tier 3: Fallback на REST API только если DataRegistry полностью недоступен
            if not price_limits or current_price <= 0:
                logger.warning(
                    f"🔴 OrderExecutor: Falling back to REST API for {symbol}"
                )
                price_limits = await self.client.get_price_limits(symbol)
                if price_limits:
                    best_bid = price_limits.get("best_bid", 0)
                    best_ask = price_limits.get("best_ask", 0)
                    current_price = price_limits.get("current_price", 0)
                    price_limits_source = "rest"
                    max_buy_price = price_limits.get("max_buy_price", 0)
                    min_sell_price = price_limits.get("min_sell_price", 0)

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

            # ✅ Дополнительная защита: если и DataRegistry, и price_limits потенциально устарели — отклоняем ордер
            try:
                pl_ts = price_limits.get("timestamp", 0) if price_limits else 0
                pl_age = (time.time() - pl_ts) if pl_ts else None
                if md_age_sec is not None and md_age_sec > 1.0:
                    if price_limits_source == "rest":
                        logger.warning(
                            f"⚠️ {symbol}: WS price stale ({md_age_sec:.3f}s), "
                            f"but REST price_limits are in use"
                        )
                    else:  # 🔴 BUG #5 FIX: 0.5 → 1.0
                        logger.error(
                            f"❌ Отклоняем размещение ордера по {symbol}: нет свежей WS-цены (DataRegistry {md_age_sec:.3f}s)"
                        )
                        raise ValueError("Stale price data: websocket is old")

                # Дополнительный контроль: если price_limits тоже старые (>1.0s)  🔴 BUG #5 FIX
                if pl_age is not None and pl_age > 1.0:  # 🔴 BUG #5 FIX: 0.5 → 1.0
                    logger.error(
                        f"❌ Отклоняем размещение ордера по {symbol}: нет свежей price_limits ({pl_age:.3f}s)"
                    )
                    raise ValueError("Stale price data: price_limits are old")

                # Инфо-лог о свежести цен при размещении ордера (раз в ~10 вызовов, чтобы не шуметь)
                if int(time.time() * 10) % 10 == 0:
                    logger.info(
                        f"PRICE_OK {symbol} md_age={md_age_sec if md_age_sec is not None else 'N/A'}s pl_age={pl_age if pl_age is not None else 'N/A'}s"
                    )
            except Exception:
                # Если не удалось оценить свежесть price_limits — продолжаем (ниже еще будут проверки)
                pass

            # Логируем расхождение между WS и REST, если использовали REST и есть ws_price
            try:
                if price_limits_source == "rest" and ws_price and current_price > 0:
                    diff_pct = abs(current_price - ws_price) / ws_price
                    if diff_pct > 0.0005:  # >0.05%
                        logger.warning(
                            f"⚠️ REST price differs from WS for {symbol}: ws={ws_price:.4f}/{ws_bid if ws_bid is not None else 0:.4f}/{ws_ask if ws_ask is not None else 0:.4f}, "
                            f"rest={current_price:.4f}/{best_bid:.4f}/{best_ask:.4f}, diff={diff_pct*100:.3f}%"
                        )
            except Exception:
                pass

            # ✅ ИСПРАВЛЕНО: Используем лучшие цены из стакана для более точного расчета
            best_bid = price_limits.get("best_bid", 0)
            best_ask = price_limits.get("best_ask", 0)
            current_price = price_limits.get("current_price", 0)
            max_buy_price = price_limits.get("max_buy_price", 0)
            min_sell_price = price_limits.get("min_sell_price", 0)

            if current_price <= 0:
                logger.error(f"❌ Неверная текущая цена для {symbol}: {current_price}")
                return 0.0

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): НИКОГДА не используем signal_price для расчета лимитной цены!
            # signal_price может быть устаревшим (например, 92728 для BTC, а текущая цена 91359)
            # Это приводит к размещению ордеров далеко от рынка (1.46% разница!)
            # ВСЕГДА используем актуальную цену из стакана (best_ask/best_bid или current_price)
            signal_price = None
            if signal:
                signal_price = signal.get("price", 0.0)
                if signal_price > 0:
                    price_diff_pct = (
                        abs(signal_price - current_price) / current_price * 100
                        if current_price > 0
                        else 100
                    )
                    # Логируем для отладки, но НЕ используем signal_price для расчета!
                    if price_diff_pct < 0.1:
                        logger.debug(
                            f"💰 signal['price']={signal_price:.2f} актуальна для {symbol} {side} "
                            f"(разница с current_price={current_price:.2f} составляет {price_diff_pct:.3f}%), "
                            f"но используем current_price из стакана"
                        )
                    else:
                        logger.warning(
                            f"⚠️ signal['price']={signal_price:.2f} устарела для {symbol} {side} "
                            f"(разница с current_price={current_price:.2f} составляет {price_diff_pct:.3f}%), "
                            f"используем current_price из стакана"
                        )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: ВСЕГДА используем current_price, НЕ signal_price!
            # base_price используется только для логирования и финальной проверки разницы
            base_price = current_price

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для скальпинга ПРИОРИТЕТ - best_ask/best_bid, затем current_price
            # base_price НЕ используется для расчета лимитной цены, только для проверок

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
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): base_price = current_price (НЕ signal_price!)
                    # Если current_price недоступен, но base_price есть - это значит current_price был установлен выше
                    # Используем base_price (который = current_price) с минимальным offset
                    min_offset = max(offset_percent, 0.01)  # Минимальный offset 0.01%
                    limit_price = base_price * (1 + min_offset / 100.0)

                    # ✅ Проверяем, что цена >= best_ask (если доступен)
                    if best_ask > 0 and limit_price < best_ask:
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} BUY ({limit_price:.2f}) ниже best_ask ({best_ask:.2f}), "
                            f"корректируем до best_ask + offset"
                        )
                        limit_price = best_ask * (1 + min_offset / 100.0)

                    logger.info(
                        f"💰 Используем base_price (current_price) для {symbol} BUY: "
                        f"base={base_price:.2f}, offset={min_offset:.3f}%, "
                        f"limit_price={limit_price:.2f} (>= best_ask={best_ask:.2f})"
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
                # 1. Проверяем лимит биржи max_buy_price (ВСЕГДА)
                # 2. Убеждаемся, что цена >= best_ask (для гарантии исполнения)
                # 3. Убеждаемся, что цена >= best_bid (защита от ошибок)

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем лимит биржи max_buy_price ВСЕГДА
                # Это критично для предотвращения ошибки 51006 (Order price is not within the price limit)
                if max_buy_price > 0:
                    if limit_price > max_buy_price:
                        # ✅ FIX (22.01.2026): Убрана слишком консервативная корректировка -0.1%
                        # Проблема: max_buy_price * 0.999 делает ордер НИЖЕ рынка при росте
                        # Решение: Используем max_buy_price - минимальный tick (0.0001% или 1 тик)
                        # Это гарантирует исполнение при движении вверх
                        safety_margin = max_buy_price * 0.00001  # 0.001% вместо 0.1%
                        corrected_price = max_buy_price - safety_margin
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} BUY ({limit_price:.2f}) превышает лимит биржи ({max_buy_price:.2f}), "
                            f"корректируем до {corrected_price:.2f} (-0.001% вместо старого -0.1% для более агрессивного входа)"
                        )
                        limit_price = corrected_price
                        logger.info(
                            f"✅ Лимитная цена для {symbol} BUY скорректирована: {limit_price:.2f} "
                            f"(было выше max_buy, max_buy_price={max_buy_price:.2f}, margin=-0.001%)"
                        )
                else:
                    logger.warning(
                        f"⚠️ max_buy_price недоступен для {symbol} BUY, пропускаем проверку лимита биржи"
                    )

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
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): base_price = current_price (НЕ signal_price!)
                    # Если current_price недоступен, но base_price есть - это значит current_price был установлен выше
                    # Используем base_price (который = current_price) с минимальным offset
                    min_offset = max(offset_percent, 0.01)
                    limit_price = base_price * (1 - min_offset / 100.0)

                    # ✅ Проверяем, что цена <= best_bid (если доступен)
                    if best_bid > 0 and limit_price > best_bid:
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} SELL ({limit_price:.2f}) выше best_bid ({best_bid:.2f}), "
                            f"корректируем до best_bid - offset"
                        )
                        limit_price = best_bid * (1 - min_offset / 100.0)

                    logger.info(
                        f"💰 Используем base_price (current_price) для {symbol} SELL: "
                        f"base={base_price:.2f}, offset={min_offset:.3f}%, "
                        f"limit_price={limit_price:.2f} (<= best_bid={best_bid:.2f})"
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
                # 1. Проверяем лимит биржи min_sell_price (ВСЕГДА, независимо от состояния best_bid)
                # 2. Убеждаемся, что цена <= best_bid (для гарантии исполнения)
                # 3. Убеждаемся, что цена <= best_ask (защита от ошибок)

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем лимит биржи min_sell_price ВСЕГДА
                # Это критично для предотвращения ошибки 51006 (Order price is not within the price limit)
                if min_sell_price > 0:
                    if limit_price < min_sell_price:
                        # ✅ FIX (22.01.2026): Убрана слишком консервативная корректировка +0.1%
                        # Проблема: min_sell_price * 1.001 делает ордер ВЫШЕ рынка при падении
                        # Решение: Используем min_sell_price + минимальный tick (0.0001% или 1 тик)
                        # Это гарантирует исполнение при движении вниз
                        safety_margin = min_sell_price * 0.00001  # 0.001% вместо 0.1%
                        corrected_price = min_sell_price + safety_margin
                        logger.warning(
                            f"⚠️ Лимитная цена для {symbol} SELL ({limit_price:.2f}) ниже лимита биржи ({min_sell_price:.2f}), "
                            f"корректируем до {corrected_price:.2f} (+0.001% вместо старого +0.1% для более агрессивного входа)"
                        )
                        limit_price = corrected_price
                        logger.info(
                            f"✅ Лимитная цена для {symbol} SELL скорректирована: {limit_price:.2f} "
                            f"(было ниже min_sell, min_sell_price={min_sell_price:.2f}, margin=+0.001%)"
                        )
                else:
                    logger.warning(
                        f"⚠️ min_sell_price недоступен для {symbol} SELL, пропускаем проверку лимита биржи"
                    )

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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (04.01.2026): Проверяем разницу между limit_price и актуальной ценой из стакана
            # Используем best_ask/best_bid для проверки, а не base_price (который может быть устаревшим)
            reference_price = 0.0
            if side.lower() == "buy":
                reference_price = best_ask if best_ask > 0 else current_price
            else:
                reference_price = best_bid if best_bid > 0 else current_price

            price_diff_pct = (
                abs(limit_price - reference_price) / reference_price * 100
                if reference_price > 0
                else 0
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если разница > 0.2% - это проблема для скальпинга!
            # Это означает что ордер размещен далеко от рынка
            if price_diff_pct > 0.2:
                logger.error(
                    f"❌ КРИТИЧЕСКАЯ ОШИБКА: Лимитная цена для {symbol} {side} слишком далеко от рынка! "
                    f"limit_price={limit_price:.2f}, reference_price={reference_price:.2f} "
                    f"(best_{'ask' if side.lower() == 'buy' else 'bid'}={best_ask if side.lower() == 'buy' else best_bid:.2f}), "
                    f"разница={price_diff_pct:.2f}%, offset={offset_percent:.3f}%, режим={regime or 'N/A'}"
                )
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Корректируем цену до безопасного значения от reference_price
                if side.lower() == "buy":
                    limit_price = reference_price * 1.001  # Максимум 0.1% выше
                else:
                    limit_price = reference_price * 0.999  # Максимум 0.1% ниже
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
                f"(best_bid={best_bid:.2f}, best_ask={best_ask:.2f}, current_price={current_price:.2f}, "
                f"signal_price={signal_price if signal_price else 'N/A'} [НЕ ИСПОЛЬЗУЕТСЯ], "
                f"spread={spread:.6f} ({spread_pct:.4f}%), offset={offset_used:.4f}% ({offset_type}), "
                f"режим={regime or 'default'}, разница от рынка={price_diff_pct:.2f}%, "
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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (24.01.2026): Проверка свежести цены перед market ордером
            # Запрашиваем текущую цену и сравниваем с ценой сигнала
            best_bid = best_ask = current_price = None
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
                current_price = (
                    float(limits.get("current"))
                    if limits and limits.get("current")
                    else None
                )

                # ✅ ЗАЩИТА: Если цена изменилась > 1.5% от сигнала - ОТМЕНЯЕМ ордер
                if current_price and hasattr(self, "_last_signal_price"):
                    signal_price = getattr(self, "_last_signal_price", {}).get(
                        symbol, current_price
                    )
                    price_divergence = (
                        abs(current_price - signal_price) / signal_price
                        if signal_price > 0
                        else 0
                    )

                    if price_divergence > 0.015:  # 1.5%
                        logger.error(
                            f"❌ ЗАЩИТА ОТ ПРОСКАЛЬЗЫВАНИЯ: {symbol} цена сигнала {signal_price:.4f} "
                            f"расходится с текущей {current_price:.4f} на {price_divergence*100:.2f}% (>1.5%) - "
                            f"ОТМЕНЯЕМ market ордер!"
                        )
                        return {
                            "success": False,
                            "error": f"Price divergence {price_divergence*100:.2f}% > 1.5%",
                            "code": "STALE_PRICE",
                        }

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
                        # Явное логирование проскальзывания при market-замене лимитного ордера
                        if getattr(self, "_is_market_replace", False):
                            logger.warning(
                                f"MARKET_REPLACE_SLIPPAGE {symbol} {side}: slippage={slippage_bps:.2f}bps (ref={ref:.4f}, fill={fill_px:.4f}), latency={latency_ms}ms, size={size:.6f}"
                            )
                            self._is_market_replace = False
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

                # FIX 2026-02-25: возвращаем fill_price и est_entry для Telegram уведомления
                # fill_px обычно None (OKX не возвращает avgPx сразу), est_entry = best_ask/bid
                est_entry = None
                if best_ask and side.lower() in ("buy", "long"):
                    est_entry = best_ask
                elif best_bid and side.lower() in ("sell", "short"):
                    est_entry = best_bid

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_type": "market",
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "fill_price": fill_px,  # None если avgPx пуст в initial response
                    "est_entry": est_entry,  # best_ask/bid в момент размещения ≈ fill price
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
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): Отключение POST_ONLY при высокой волатильности (>0.8-1%)  🔴 BUG #6 FIX
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
                            if (
                                price_diff_pct > 0.8
                            ):  # 🔴 BUG #6 FIX: 0.5% → 0.8% (more lenient)
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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Получение bid-ask спреда перед размещением
            # Проблема: 38% ордеров отказываются с ошибкой 51006 (price out of range ±2%)
            # Решение: Получаем текущий bid-ask и размещаем цену ВНУТРИ спреда, а не на краях
            try:
                # Получаем текущий спред (bid-ask)
                # ✅ ИСПРАВЛЕНО (10.01.2026): Используем data_registry вместо несуществующего client.get_market_data()
                market_data = None
                if self.data_registry:
                    market_data = await self.data_registry.get_market_data(symbol)

                if not market_data and self.client:
                    # Fallback на REST API если DataRegistry недоступен
                    try:
                        ticker = await self.client.get_ticker(symbol)
                        if ticker:
                            market_data = ticker
                    except Exception as e:
                        logger.debug(
                            f"⚠️ order_executor: Fallback на REST API ошибка: {e}"
                        )

                if market_data:
                    # 🔴 BUG #3 FIX: Маппирование current_tick.bid/ask → bid_price/ask_price
                    # WebSocketCoordinator пишет current_tick (bid/ask)
                    # OrderExecutor читает bid_price/ask_price
                    current_tick = market_data.get("current_tick")
                    if (
                        current_tick
                        and hasattr(current_tick, "bid")
                        and hasattr(current_tick, "ask")
                    ):
                        current_bid = (
                            float(current_tick.bid) if current_tick.bid else 0.0
                        )
                        current_ask = (
                            float(current_tick.ask) if current_tick.ask else 0.0
                        )
                    else:
                        # Fallback на прямое чтение если current_tick недоступен
                        current_bid = float(
                            market_data.get("bid_price") or market_data.get("bidPx", 0)
                        )
                        current_ask = float(
                            market_data.get("ask_price") or market_data.get("askPx", 0)
                        )

                    if current_bid > 0 and current_ask > 0:
                        # Параметры для размещения цены
                        spread_pct = ((current_ask - current_bid) / current_bid) * 100.0

                        if side.lower() == "buy":
                            # Для BUY: размещаем ниже текущего ask, но выше mid + 0.1% буфера
                            mid_price = (current_bid + current_ask) / 2
                            buffer_price = mid_price * 1.001  # +0.1% буфер от середины
                            price = min(price, buffer_price)  # Не выше буфера
                            logger.debug(
                                f"🔍 BUY ордер {symbol}: spread={spread_pct:.3f}%, bid={current_bid:.2f}, ask={current_ask:.2f}, "
                                f"mid={mid_price:.2f}, buffer={buffer_price:.2f}, final_price={price:.2f}"
                            )
                        else:  # SELL
                            # Для SELL: размещаем выше текущего bid, но ниже mid - 0.1% буфера
                            mid_price = (current_bid + current_ask) / 2
                            buffer_price = mid_price * 0.999  # -0.1% буфер от середины
                            price = max(price, buffer_price)  # Не ниже буфера
                            logger.debug(
                                f"🔍 SELL ордер {symbol}: spread={spread_pct:.3f}%, bid={current_bid:.2f}, ask={current_ask:.2f}, "
                                f"mid={mid_price:.2f}, buffer={buffer_price:.2f}, final_price={price:.2f}"
                            )
            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось получить bid-ask спред для {symbol}: {e}, продолжаем без оптимизации"
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

                # ✅ OKX: Client order ID already exists (51016) -> проверяем ордер по clOrdId
                if error_code == "51016" or "51016" in str(error_code):
                    try:
                        existing = await self.client.get_order_by_clordid(
                            symbol, cl_ord_id
                        )
                        if existing:
                            existing_order_id = existing[0].get("ordId")
                            logger.warning(
                                f"⚠️ clOrdId уже существует, ордер найден на бирже: {existing_order_id}"
                            )
                            return {
                                "success": True,
                                "order_id": existing_order_id,
                                "order_type": "limit",
                                "symbol": symbol,
                                "side": side,
                                "size": size,
                                "price": price,
                                "timestamp": datetime.now(),
                                "recovered": True,
                            }
                    except Exception as lookup_error:
                        logger.warning(
                            f"⚠️ Не удалось проверить ордер по clOrdId: {lookup_error}"
                        )

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
            tp_sl_result = await self._calculate_tp_sl_prices(signal, size)
            if tp_sl_result is None:
                logger.error(
                    f"🚫 Не удалось рассчитать TP/SL для {symbol}, " f"OCO ордер отменён"
                )
                return {"success": False, "error": "TP/SL calculation failed"}
            tp_price, sl_price = tp_sl_result

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

                # Telegram: уведомление о входе
                if self.telegram:
                    size_usd = size * signal.get("price", 0.0)
                    asyncio.create_task(
                        self.telegram.send_trade_open(
                            signal=signal,
                            tp_price=tp_price,
                            sl_price=sl_price,
                            size_usd=size_usd,
                        )
                    )

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
    ) -> Optional[Tuple[float, float]]:
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
                # 🔴 BUG #9 FIX: убираем магические цены BTC/ETH, берем реальные данные
                try:
                    # Попытка 1: DataRegistry (WebSocket актуальная цена)
                    if hasattr(self, "data_registry") and self.data_registry:
                        price_from_registry = await self.data_registry.get_price(symbol)
                        if price_from_registry and price_from_registry > 0:
                            entry_price = price_from_registry

                    # Попытка 2: REST ticker
                    if entry_price == 0.0:
                        import aiohttp

                        inst_id = f"{symbol}-SWAP"
                        url = (
                            f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}"
                        )
                        async with aiohttp.ClientSession() as session:
                            async with session.get(url) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    if data.get("code") == "0" and data.get("data"):
                                        ticker = data["data"][0]
                                        entry_price = float(ticker.get("last", "0"))

                    # Попытка 3: price_limits current_price
                    if entry_price == 0.0 and hasattr(self, "client") and self.client:
                        try:
                            price_limits = await self.client.get_price_limits(symbol)
                            if price_limits and price_limits.get("current_price"):
                                entry_price = float(price_limits.get("current_price"))
                        except Exception:
                            pass

                except Exception as e:
                    logger.error(f"❌ Не удалось получить цену для {symbol}: {e}")

                if entry_price == 0.0:
                    logger.error(
                        f"❌ BUG #9: Не удалось получить актуальную цену для {symbol}, отменяем расчет TP/SL"
                    )
                    raise ValueError(
                        f"Cannot calculate TP/SL without entry price for {symbol}"
                    )

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
            # FIX 2026-02-22 P1.3: передаём symbol чтобы by_symbol overrides (sl/tp ATR multiplier) применялись
            regime_params = self._get_regime_params(regime, symbol=symbol)

            # 🎯 АДАПТИВНЫЕ МУЛЬТИПЛИКАТОРЫ
            if regime_params:
                tp_multiplier = regime_params.get("tp_atr_multiplier", 0.6)
                sl_multiplier = regime_params.get("sl_atr_multiplier", 0.4)
            else:
                # Fallback на конфигурацию
                # ✅ ИСПРАВЛЕНО: Проверяем как dict и как Pydantic модель
                if isinstance(self.scalping_config, dict):
                    tp_multiplier = float(self.scalping_config.get("tp_percent", 0.3))
                    sl_multiplier = float(self.scalping_config.get("sl_percent", 0.2))
                else:
                    tp_multiplier = float(
                        getattr(self.scalping_config, "tp_percent", 0.3)
                    )
                    sl_multiplier = float(
                        getattr(self.scalping_config, "sl_percent", 0.2)
                    )

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

            # ✅ FIX #2: Повторная проверка SL floor после применения arm_override
            # Иногда arm_override содержит sl_atr_multiplier который даёт слишком узкий SL
            sl_floor_pct = (
                float(regime_params.get("sl_percent", 0) if regime_params else 0)
                / 100.0
            )
            if sl_floor_pct > 0:
                sl_floor_abs = entry_price * sl_floor_pct
                if sl_distance < sl_floor_abs:
                    old_sl_distance = sl_distance
                    sl_distance = sl_floor_abs
                    logger.info(
                        f"⚠️ FIX#2: SL floor reapplied after arm_override: "
                        f"{old_sl_distance/entry_price*100:.2f}% → {sl_distance/entry_price*100:.2f}% "
                        f"(floor={sl_floor_pct*100:.2f}%) для {symbol} {regime}"
                    )

            # FIX 2026-02-22 P0.1: применяем tp_percent как минимальный TP (зеркально sl_percent).
            # Без этого TP остаётся ATR-based (~0.2-0.4%) при SL floored 1.0-1.5% → R:R 0.2:1 → гарантированный убыток.
            # Config уже содержит правильные значения: trending tp_percent=4.0%/sl=1.2% → R:R 3.3:1
            tp_percent_value = None
            if regime_params:
                tp_percent_value = regime_params.get("tp_percent") or regime_params.get(
                    "tp_min_percent"
                )
            if tp_percent_value is None:
                tp_percent_value = getattr(self.scalping_config, "tp_percent", 2.4)
                logger.warning(
                    f"⚠️ FALLBACK: Используется глобальный tp_percent={tp_percent_value:.2f}% для {symbol} "
                    f"(regime={regime})"
                )

            tp_percent_abs = entry_price * (float(tp_percent_value) / 100.0)
            if tp_distance < tp_percent_abs:
                old_tp_distance = tp_distance
                tp_distance = tp_percent_abs
                logger.info(
                    f"⚠️ ATR-based TP слишком мал ({old_tp_distance/entry_price*100:.2f}%) "
                    f"→ применяем tp_percent floor ({float(tp_percent_value):.2f}%) для {symbol} "
                    f"(regime={regime}, итоговый R:R={tp_distance/sl_distance:.2f}:1)"
                )
            else:
                logger.info(
                    f"✅ ATR-based TP ({tp_distance/entry_price*100:.2f}%) для {symbol} "
                    f"выше tp_percent floor ({float(tp_percent_value):.2f}%) "
                    f"(regime={regime}, итоговый R:R={tp_distance/sl_distance:.2f}:1)"
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
                    logger.critical(
                        f"❌ CRITICAL: не удалось получить цену для {symbol}, "
                        f"TP/SL расчёт невозможен"
                    )
                    return None  # Caller должен обработать None как отказ
            if entry_price is None or entry_price <= 0:
                logger.critical(
                    f"❌ CRITICAL: невалидная цена {entry_price} для {symbol}"
                )
                return None

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
                # ✅ ИСПРАВЛЕНО: Проверяем как dict и как Pydantic модель
                if isinstance(self.scalping_config, dict):
                    adaptive_regime = self.scalping_config.get("adaptive_regime", {})
                else:
                    adaptive_regime = (
                        getattr(self.scalping_config, "adaptive_regime", {}) or {}
                    )

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

    async def amend_order_price(
        self, symbol: str, order_id: str, new_price: float
    ) -> Dict[str, Any]:
        """Изменение цены лимитного ордера через batch amend (1 ордер)."""
        try:
            if new_price <= 0:
                return {"success": False, "error": "invalid new_price"}

            inst_id = f"{symbol}-SWAP"
            amend_item = {
                "instId": inst_id,
                "ordId": str(order_id),
                "newPx": str(new_price),
            }

            logger.info(f"🔄 Amend price: {symbol} ordId={order_id} → {new_price:.6f}")

            result = await self.client.batch_amend_orders([amend_item])

            if result and str(result.get("code")) == "0":
                logger.info(f"✅ Цена ордера {order_id} изменена на {new_price:.6f}")
                return {"success": True, "order_id": order_id, "new_price": new_price}

            msg = result.get("msg") if isinstance(result, dict) else "Unknown error"
            logger.warning(f"⚠️ Не удалось изменить цену ордера {order_id}: {msg}")
            return {"success": False, "error": msg}
        except Exception as e:
            logger.error(f"Ошибка amend_order_price: {e}")
            return {"success": False, "error": str(e)}

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
