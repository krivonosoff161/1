"""
Signal Coordinator для Futures торговли.

Управляет обработкой торговых сигналов:
- Проверка сигналов для символов
- Валидация сигналов
- Исполнение сигналов
- Обработка списка сигналов
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger


class SignalCoordinator:
    """
    Координатор обработки торговых сигналов для Futures торговли.

    Управляет генерацией, валидацией и исполнением торговых сигналов.
    """

    def __init__(
        self,
        client,
        scalping_config,
        signal_generator,
        config_manager,
        order_executor,
        position_manager,
        margin_calculator,
        slippage_guard,
        max_size_limiter,
        trading_statistics,
        risk_manager,
        debug_logger,
        active_positions_ref: Dict[str, Dict[str, Any]],
        last_orders_cache_ref: Dict[str, Dict[str, Any]],
        active_orders_cache_ref: Dict[str, Dict[str, Any]],
        last_orders_check_time_ref: Dict[str, float],
        signal_locks_ref: Dict[str, asyncio.Lock],
        funding_monitor,
        config,
        trailing_sl_coordinator,
        total_margin_used_ref,
        get_used_margin_callback: Optional[Callable[[], Awaitable[float]]] = None,
        get_position_callback: Optional[Callable[[str], Dict[str, Any]]] = None,
        close_position_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        normalize_symbol_callback: Optional[Callable[[str], str]] = None,
        initialize_trailing_stop_callback: Optional[
            Callable[[str, float, str, float, Dict[str, Any]], Any]
        ] = None,
        entry_manager=None,  # ✅ НОВОЕ: EntryManager для централизованного открытия позиций
        data_registry=None,  # ✅ НОВОЕ: DataRegistry для централизованного чтения данных
        adaptive_leverage=None,  # ✅ ИСПРАВЛЕНИЕ #3: AdaptiveLeverage для адаптивного левериджа
        position_scaling_manager=None,  # ✅ НОВОЕ: PositionScalingManager для лестничного добавления
        parameter_provider=None,  # ✅ НОВОЕ (26.12.2025): ParameterProvider для единого доступа к параметрам
    ):
        """
        Инициализация SignalCoordinator.

        Args:
            client: Клиент биржи
            scalping_config: Конфигурация скальпинга
            signal_generator: Генератор сигналов
            config_manager: Менеджер конфигурации
            order_executor: Исполнитель ордеров
            position_manager: Менеджер позиций
            margin_calculator: Калькулятор маржи
            slippage_guard: Защита от проскальзывания
            max_size_limiter: Ограничитель размера позиций
            trading_statistics: Статистика торговли
            risk_manager: Менеджер рисков
            debug_logger: Логгер для отладки
            active_positions_ref: Ссылка на активные позиции
            last_orders_cache_ref: Ссылка на кэш последних ордеров
            active_orders_cache_ref: Ссылка на кэш активных ордеров
            last_orders_check_time_ref: Ссылка на время последней проверки ордеров
            signal_locks_ref: Ссылка на блокировки для символов
            get_position_callback: Функция для получения позиции по символу
            close_position_callback: Функция для закрытия позиции
            normalize_symbol_callback: Функция для нормализации символа
        """
        self.client = client
        self.scalping_config = scalping_config
        self.signal_generator = signal_generator
        self.config_manager = config_manager  # Оставляем для обратной совместимости
        self.parameter_provider = parameter_provider  # ✅ НОВОЕ (26.12.2025): ParameterProvider для единого доступа к параметрам
        self.order_executor = order_executor
        self.position_manager = position_manager
        self.margin_calculator = margin_calculator
        self.slippage_guard = slippage_guard
        self.max_size_limiter = max_size_limiter
        self.trading_statistics = trading_statistics
        self.risk_manager = risk_manager
        self.debug_logger = debug_logger
        self.active_positions_ref = active_positions_ref
        self.last_orders_cache_ref = last_orders_cache_ref
        self.active_orders_cache_ref = active_orders_cache_ref
        self.last_orders_check_time_ref = last_orders_check_time_ref
        self.signal_locks_ref = signal_locks_ref
        self.funding_monitor = funding_monitor
        self.config = config
        self.trailing_sl_coordinator = trailing_sl_coordinator
        self.total_margin_used_ref = total_margin_used_ref
        self.get_used_margin_callback = get_used_margin_callback
        self.get_position_callback = get_position_callback
        self.close_position_callback = close_position_callback
        self.normalize_symbol_callback = normalize_symbol_callback
        self.initialize_trailing_stop_callback = initialize_trailing_stop_callback
        # ✅ НОВОЕ: EntryManager для централизованного открытия позиций
        self.entry_manager = entry_manager
        # ✅ НОВОЕ: DataRegistry для централизованного чтения данных
        self.data_registry = data_registry
        # ✅ ИСПРАВЛЕНИЕ #3: AdaptiveLeverage для адаптивного левериджа
        self.adaptive_leverage = adaptive_leverage
        # ✅ НОВОЕ: PositionScalingManager для лестничного добавления
        self.position_scaling_manager = position_scaling_manager
        
        # ✅ НОВОЕ (26.12.2025): ConversionMetrics для отслеживания конверсии
        self.conversion_metrics = None

        # Время последнего сигнала по символу: {symbol: timestamp}
        self._last_signal_time: Dict[str, float] = {}
        # ✅ КРИТИЧЕСКОЕ: Throttling для избыточных предупреждений
        self._last_warning_time: Dict[
            str, float
        ] = {}  # Время последнего предупреждения для каждого символа
        self._warning_throttle_seconds: float = (
            30.0  # Минимум 30 секунд между одинаковыми предупреждениями
        )

        logger.info("✅ SignalCoordinator initialized")

    def set_conversion_metrics(self, conversion_metrics):
        """
        ✅ НОВОЕ (26.12.2025): Установить ConversionMetrics для отслеживания конверсии сигналов.

        Args:
            conversion_metrics: Экземпляр ConversionMetrics
        """
        self.conversion_metrics = conversion_metrics
        logger.debug("✅ SignalCoordinator: ConversionMetrics установлен")

    async def process_signals(self, signals: List[Dict[str, Any]]):
        """Обработка торговых сигналов"""
        try:
            # 🔄 НОВОЕ: отключаем legacy-обработку, чтобы не дублировать реальные сигналы,
            # которые приходят из WebSocket (_check_for_signals)
            if not getattr(self.scalping_config, "use_legacy_signal_processing", False):
                logger.debug(
                    "⏭️ Legacy process_signals пропущен (используется realtime обработка сигналов через WebSocket)."
                )
                return

            for signal in signals:
                symbol = signal.get("symbol")
                side = signal.get("side")
                strength = signal.get("strength", 0)

                # ✅ FIX: Circuit breaker - проверяем блокировку символа
                if self.risk_manager and self.risk_manager.is_symbol_blocked(symbol):
                    # ✅ НОВОЕ (26.12.2025): Детальное логирование блокировки
                    logger.warning(
                        f"🚫 БЛОКИРОВКА СИГНАЛА: {symbol} {side.upper()} - "
                        f"символ заблокирован RiskManager (последовательные убытки)"
                    )
                    continue

                # ✅ КОНФИГУРИРУЕМАЯ Блокировка SHORT/LONG сигналов по конфигу (по умолчанию разрешены обе стороны)
                signal_side = side.lower() if side else ""
                allow_short = getattr(
                    self.scalping_config, "allow_short_positions", True
                )
                allow_long = getattr(self.scalping_config, "allow_long_positions", True)

                if signal_side == "sell" and not allow_short:
                    logger.debug(
                        f"⛔ SHORT сигнал заблокирован для {symbol}: "
                        f"allow_short_positions={allow_short} (только LONG стратегия)"
                    )
                    continue
                elif signal_side == "buy" and not allow_long:
                    logger.debug(
                        f"⛔ LONG сигнал заблокирован для {symbol}: "
                        f"allow_long_positions={allow_long} (только SHORT стратегия)"
                    )
                    continue

                # ✅ ИСПРАВЛЕНО (27.12.2025): Используем параметры из конфига для каждого режима
                # Приоритет: режим-специфичные -> базовый min_signal_strength -> fallback
                
                # Получаем текущий режим для символа
                regime = signal.get("regime")
                if not regime and hasattr(self.signal_generator, "regime_managers"):
                    if symbol in getattr(self.signal_generator, "regime_managers", {}):
                        regime_manager = self.signal_generator.regime_managers.get(
                            symbol
                        )
                        if regime_manager:
                            regime_obj = regime_manager.get_current_regime()
                            if regime_obj:
                                regime = (
                                    regime_obj.value.lower()
                                    if hasattr(regime_obj, "value")
                                    else str(regime_obj).lower()
                                )

                # Если режим не найден в per-symbol ARM, пробуем общий
                if not regime and hasattr(self.signal_generator, "regime_manager"):
                    regime_manager = getattr(
                        self.signal_generator, "regime_manager", None
                    )
                    if regime_manager:
                        regime_obj = regime_manager.get_current_regime()
                        if regime_obj:
                            regime = (
                                regime_obj.value.lower()
                                if hasattr(regime_obj, "value")
                                else str(regime_obj).lower()
                            )

                # Используем режим-специфичные параметры из конфига, если заданы
                min_strength = None
                if regime:
                    regime_lower = regime.lower()
                    if regime_lower == "ranging":
                        min_strength = getattr(
                            self.scalping_config, "min_signal_strength_ranging", None
                        )
                    elif regime_lower == "trending":
                        min_strength = getattr(
                            self.scalping_config, "min_signal_strength_trending", None
                        )
                    elif regime_lower == "choppy":
                        min_strength = getattr(
                            self.scalping_config, "min_signal_strength_choppy", None
                        )
                
                # Fallback на базовый min_signal_strength из scalping_config
                if min_strength is None:
                    min_strength = getattr(
                        self.scalping_config, "min_signal_strength", 0.3
                    )
                
                # Преобразуем в float
                min_strength = float(min_strength) if min_strength is not None else 0.3
                
                logger.debug(
                    f"🔍 SignalCoordinator: {symbol} (режим: {regime or 'unknown'}), "
                    f"используем min_signal_strength={min_strength:.2f} "
                    f"(из конфига)"
                )

                if strength < min_strength:
                    # ✅ НОВОЕ (26.12.2025): Детальное логирование блокировки сигналов
                    logger.warning(
                        f"🚫 БЛОКИРОВКА СИГНАЛА: {symbol} {side.upper()} - "
                        f"strength={strength:.3f} < min={min_strength:.3f} "
                        f"(режим={regime or 'unknown'}, "
                        f"базовый_порог={self.scalping_config.min_signal_strength:.3f})"
                    )
                    continue

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем направление позиции!
                # На OKX Futures несколько ордеров в ОДНОМ направлении объединяются в ОДНУ позицию
                # Поэтому нужно блокировать новые ордера, если уже есть позиция в этом направлении
                max_positions_per_symbol = getattr(
                    self.scalping_config, "max_positions_per_symbol", 4
                )
                allow_concurrent = getattr(
                    self.scalping_config, "allow_concurrent_positions", False
                )

                try:
                    # Получаем реальные позиции с биржи
                    all_positions = await self.client.get_positions()
                    signal_side = signal.get("side", "").lower()  # "buy" или "sell"

                    # Определяем направление позиции для сигнала
                    signal_position_side = "long" if signal_side == "buy" else "short"

                    symbol_positions = [
                        p
                        for p in all_positions
                        if (
                            p.get("instId", "").replace("-SWAP", "") == symbol
                            or p.get("instId", "") == symbol
                        )
                        and abs(float(p.get("pos", "0"))) > 0.000001
                    ]

                    # Проверяем, есть ли уже позиция в направлении сигнала
                    position_in_signal_direction = None
                    for pos in symbol_positions:
                        pos_side = pos.get("posSide", "").lower()
                        pos_size = float(pos.get("pos", "0"))

                        # Определяем направление позиции
                        if pos_size > 0:
                            actual_side = "long"
                        else:
                            actual_side = "short"

                        # Если позиция в том же направлении, что и сигнал
                        if actual_side == signal_position_side:
                            position_in_signal_direction = pos
                            break

                    if position_in_signal_direction:
                        # ✅ ИЗМЕНЕНИЕ: Позиция уже есть в направлении сигнала
                        # Проверяем возможность добавления через PositionScalingManager
                        pos_size = abs(
                            float(position_in_signal_direction.get("pos", "0"))
                        )

                        # ✅ НОВОЕ: Если PositionScalingManager доступен, проверяем возможность добавления
                        if self.position_scaling_manager:
                            try:
                                # Получаем баланс для проверки
                                balance = await self.client.get_balance()

                                # Получаем balance_profile
                                balance_profile = None
                                if self.data_registry:
                                    balance_data = (
                                        await self.data_registry.get_balance()
                                    )
                                    if balance_data:
                                        balance_profile = balance_data.get("profile")
                                if not balance_profile:
                                    balance_profile = (
                                        self.config_manager.get_balance_profile(
                                            balance
                                        ).get("name", "medium")
                                    )

                                # Получаем regime
                                regime = signal.get("regime")
                                if not regime and hasattr(
                                    self.signal_generator, "regime_manager"
                                ):
                                    regime_manager = getattr(
                                        self.signal_generator, "regime_manager", None
                                    )
                                    if regime_manager:
                                        regime = regime_manager.get_current_regime()

                                # Проверяем возможность добавления
                                can_add_result = await self.position_scaling_manager.can_add_to_position(
                                    symbol, balance, balance_profile, regime
                                )

                                if can_add_result.get("can_add", False):
                                    # Рассчитываем базовый размер позиции для лестницы
                                    # Используем текущий расчет размера как базовый
                                    base_size_usd = None
                                    try:
                                        # Получаем детали инструмента для расчета
                                        details = (
                                            await self.client.get_instrument_details(
                                                symbol
                                            )
                                        )
                                        ct_val = details.get("ctVal", 0.01)
                                        current_price = signal.get("price", 0)
                                        if current_price > 0:
                                            # Используем текущий размер позиции как базовый для лестницы
                                            # Или можно использовать расчет из risk_manager
                                            size_in_coins = pos_size * ct_val
                                            base_size_usd = (
                                                size_in_coins * current_price
                                            )
                                    except Exception as e:
                                        logger.warning(
                                            f"⚠️ Ошибка расчета base_size_usd для {symbol}: {e}"
                                        )

                                    if base_size_usd:
                                        # Рассчитываем размер добавления
                                        addition_size_usd = await self.position_scaling_manager.calculate_next_addition_size(
                                            symbol,
                                            base_size_usd,
                                            signal,
                                            balance,
                                            balance_profile,
                                            regime,
                                        )

                                        if addition_size_usd:
                                            logger.info(
                                                f"✅ [POSITION_SCALING] {symbol}: Разрешено добавление | "
                                                f"size=${addition_size_usd:.2f}, "
                                                f"добавлений: {can_add_result.get('addition_count', 0)}"
                                            )
                                            # Продолжаем выполнение сигнала с рассчитанным размером добавления
                                            # Размер будет переопределен в процессе размещения ордера
                                            signal[
                                                "addition_size_usd"
                                            ] = addition_size_usd
                                            signal["is_addition"] = True
                                        else:
                                            # ✅ ИСПРАВЛЕНИЕ: Это может быть нормальная ситуация, логируем как debug
                                            logger.debug(
                                                f"🔍 [POSITION_SCALING] {symbol}: Не удалось рассчитать размер добавления (возможно недостаточно данных), блокируем"
                                            )
                                            continue
                                    else:
                                        # ✅ ИСПРАВЛЕНИЕ: Это может быть нормальная ситуация, логируем как debug
                                        logger.debug(
                                            f"🔍 [POSITION_SCALING] {symbol}: Не удалось рассчитать base_size_usd (возможно недостаточно данных), блокируем"
                                        )
                                        continue
                                else:
                                    # Нельзя добавлять - блокируем
                                    # ✅ ИСПРАВЛЕНИЕ: Это нормальная ситуация, не логируем как warning
                                    reason = can_add_result.get("reason", "unknown")
                                    logger.debug(
                                        f"🔍 [POSITION_SCALING] {symbol}: Добавление заблокировано - {reason}"
                                    )
                                    continue

                            except Exception as e:
                                logger.error(
                                    f"❌ [POSITION_SCALING] Ошибка проверки возможности добавления для {symbol}: {e}",
                                    exc_info=True,
                                )
                                # При ошибке блокируем (безопаснее)
                                continue
                        else:
                            # ✅ КРИТИЧЕСКОЕ: Позиция уже есть в направлении сигнала
                            # На OKX Futures новый ордер в том же направлении просто увеличит размер позиции
                            # Это означает, что мы НЕ создаем новую позицию, а увеличиваем существующую
                            # Поэтому блокируем, чтобы не накапливать комиссию на одной позиции (если PositionScalingManager не доступен)
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем max_size_limiter с реальными данными с биржи
                            # Это гарантирует, что если позиция есть на бирже, она будет отражена в max_size_limiter
                            if symbol not in self.max_size_limiter.position_sizes:
                                # Позиция есть на бирже, но не в max_size_limiter - добавляем
                                try:
                                    entry_price = float(
                                        position_in_signal_direction.get("avgPx", "0")
                                    ) or float(
                                        position_in_signal_direction.get("markPx", "0")
                                    )
                                    if entry_price > 0:
                                        # Получаем ctVal для конвертации
                                        if hasattr(
                                            self.client, "get_instrument_details"
                                        ):
                                            try:
                                                details = await self.client.get_instrument_details(
                                                    symbol
                                                )
                                                ct_val = float(
                                                    details.get("ctVal", "1.0")
                                                )
                                                size_in_coins = pos_size * ct_val
                                                size_usd = size_in_coins * entry_price
                                                self.max_size_limiter.add_position(
                                                    symbol, size_usd
                                                )
                                                logger.debug(
                                                    f"🔄 Позиция {symbol} добавлена в max_size_limiter из реальных данных биржи: {size_usd:.2f} USD"
                                                )
                                            except Exception as detail_error:
                                                logger.debug(
                                                    f"⚠️ Не удалось получить детали инструмента для {symbol}: {detail_error}"
                                                )
                                except Exception as e:
                                    logger.debug(
                                        f"⚠️ Не удалось обновить max_size_limiter для {symbol}: {e}"
                                    )

                            # ✅ ЛОГИРОВАНИЕ: Показываем, было ли переключение направления ADX
                            original_side = signal.get("original_side", "")
                            side_switched = signal.get("side_switched_by_adx", False)
                            if side_switched and original_side:
                                original_position_side = (
                                    "long"
                                    if original_side.lower() == "buy"
                                    else "short"
                                )
                                logger.warning(
                                    f"⚠️ Позиция {symbol} {signal_position_side.upper()} УЖЕ ОТКРЫТА на бирже (size={pos_size}), "
                                    f"БЛОКИРУЕМ новый {signal_side.upper()} ордер "
                                    f"(ADX переключил направление с {original_position_side.upper()} → {signal_position_side.upper()}, "
                                    f"но позиция уже открыта в этом направлении. "
                                    f"На OKX Futures ордера в одном направлении объединяются, комиссия накапливается!)"
                                )
                            else:
                                logger.warning(
                                    f"⚠️ Позиция {symbol} {signal_position_side.upper()} УЖЕ ОТКРЫТА на бирже (size={pos_size}), "
                                    f"БЛОКИРУЕМ новый {signal_side.upper()} ордер "
                                    f"(на OKX Futures ордера в одном направлении объединяются в одну позицию, комиссия накапливается!)"
                                )
                            continue
                    elif len(symbol_positions) == 0:
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Позиции нет на бирже - очищаем max_size_limiter если там есть устаревшие данные
                        if symbol in self.max_size_limiter.position_sizes:
                            logger.debug(
                                f"🔄 Позиция {symbol} отсутствует на бирже, но есть в max_size_limiter, "
                                f"очищаем устаревшие данные перед открытием новой позиции"
                            )
                            self.max_size_limiter.remove_position(symbol)
                    elif len(symbol_positions) > 0:
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Есть позиции - блокируем новые сигналы вместо закрытия
                        # Проверяем, есть ли противоположные позиции (LONG и SHORT одновременно)
                        has_long = any(
                            p.get("posSide", "").lower() == "long"
                            or (
                                float(p.get("pos", "0")) > 0
                                and p.get("posSide", "").lower()
                                not in ["long", "short"]
                            )
                            for p in symbol_positions
                        )
                        has_short = any(
                            p.get("posSide", "").lower() == "short"
                            or (
                                float(p.get("pos", "0")) < 0
                                and p.get("posSide", "").lower()
                                not in ["long", "short"]
                            )
                            for p in symbol_positions
                        )

                        # ✅ НОВОЕ: Разрешаем LONG и SHORT одновременно, разрешаем суммирование ордеров
                        # Подсчитываем ордера в том же направлении что и сигнал
                        signal_position_side = signal.get(
                            "position_side", "long"
                        ).lower()
                        same_direction_count = 0
                        for pos in symbol_positions:
                            pos_side_raw = pos.get("posSide", "").lower()
                            pos_raw = float(pos.get("pos", "0"))
                            if pos_side_raw in ["long", "short"]:
                                pos_side = pos_side_raw
                            else:
                                pos_side = "long" if pos_raw > 0 else "short"

                            if pos_side == signal_position_side:
                                same_direction_count += 1

                        # Если уже 5 ордеров в том же направлении → полное закрытие позиции
                        if same_direction_count >= 5:
                            logger.info(
                                f"🔄 {symbol}: Достигнут лимит 5 ордеров в направлении {signal_position_side.upper()}, "
                                f"закрываем все позиции перед новым сигналом"
                            )
                            # Закрываем все позиции по символу
                            if hasattr(self, "orchestrator") and self.orchestrator:
                                if hasattr(self.orchestrator, "position_manager"):
                                    await self.orchestrator.position_manager.close_position_manually(
                                        symbol, reason="max_orders_reached"
                                    )
                            # Продолжаем открытие новой позиции после закрытия
                        elif same_direction_count > 0:
                            logger.debug(
                                f"📊 {symbol}: Уже есть {same_direction_count} ордер(ов) в направлении {signal_position_side.upper()}, "
                                f"разрешаем суммирование (до 5)"
                            )
                            # Разрешаем открытие - ордера суммируются

                        # Разрешаем LONG и SHORT одновременно - бот сам закроет когда увидит разворот
                        if has_long and has_short:
                            logger.debug(
                                f"📊 {symbol}: Есть LONG и SHORT одновременно - разрешаем (хеджирование)"
                            )
                            # Разрешаем - бот сам закроет когда увидит разворот

                        # Проверяем общий лимит позиций по символу (максимум 5)
                        if len(symbol_positions) >= 5:
                            logger.debug(
                                f"⚠️ Достигнут общий лимит позиций по {symbol}: {len(symbol_positions)}/5, "
                                f"БЛОКИРУЕМ новые сигналы"
                            )
                            continue
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка проверки позиций для {symbol}: {e}")
                    # При ошибке - лучше пропустить, чем создать дубликат
                    continue

                # Валидация сигнала
                if await self.validate_signal(signal):
                    await self.execute_signal(signal)

        except Exception as e:
            logger.error(f"Ошибка обработки сигналов: {e}")

    async def validate_signal(self, signal: Dict[str, Any]) -> bool:
        """Валидация торгового сигнала"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")

            # ✅ НОВОЕ: Получение баланса из DataRegistry
            balance = None
            if self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    balance = balance_data.get("balance") if balance_data else None
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка получения баланса из DataRegistry: {e}")

            # Fallback: если DataRegistry не доступен или нет данных
            if balance is None:
                balance = await self.client.get_balance()

            # Расчет максимального размера позиции
            current_price = signal.get("price", 0)
            max_size = self.margin_calculator.calculate_max_position_size(
                balance, current_price
            )

            # Проверка минимального размера
            min_size = self.scalping_config.min_position_size
            if max_size < min_size:
                logger.warning(
                    f"Максимальный размер позиции {max_size:.6f} меньше минимального {min_size:.6f}"
                )
                return False

            # Валидация через Slippage Guard
            (
                is_valid,
                reason,
            ) = await self.slippage_guard.validate_order_before_placement(
                symbol=symbol,
                side=side,
                order_type="market",
                price=None,
                size=max_size,
                client=self.client,
            )

            if not is_valid:
                logger.warning(f"Сигнал не прошел валидацию: {reason}")
                return False

            return True

        except Exception as e:
            logger.error(f"Ошибка валидации сигнала: {e}")
            return False

    async def execute_signal(self, signal: Dict[str, Any]):
        """Исполнение торгового сигнала"""
        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            strength = signal.get("strength", 0)

            logger.info(f"🎯 Исполнение сигнала: {symbol} {side} (сила: {strength:.2f})")

            # ✅ RATE LIMIT: per-symbol cooldown между входами
            try:
                cooldown = (
                    getattr(self.scalping_config, "signal_cooldown_seconds", 0.0) or 0.0
                )
                if cooldown and cooldown > 0:
                    now_ts = datetime.utcnow().timestamp()
                    if not hasattr(self, "_last_signal_time"):
                        self._last_signal_time = {}
                    last_ts = self._last_signal_time.get(symbol)
                    if last_ts and (now_ts - last_ts) < cooldown:
                        wait_left = cooldown - (now_ts - last_ts)
                        logger.debug(
                            f"⏳ Cooldown: по {symbol} прошло лишь {now_ts - last_ts:.2f}s < {cooldown:.2f}s, "
                            f"ждём ещё {wait_left:.2f}s, пропускаем вход"
                        )
                        return
                    # записываем время попытки входа
                    self._last_signal_time[symbol] = now_ts
            except Exception as e:
                logger.debug(f"⚠️ Не удалось применить cooldown для {symbol}: {e}")

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #7: Улучшенная логика замены позиций
            # Проверяем позиции на бирже и определяем, нужно ли заменять
            try:
                positions = await self.client.get_positions()
                inst_id = f"{symbol}-SWAP"
                symbol_positions = [
                    p
                    for p in positions
                    if (
                        p.get("instId", "") == inst_id
                        or p.get("instId", "") == symbol
                        or p.get("instId", "").replace("-", "")
                        == inst_id.replace("-", "")
                    )
                    and abs(float(p.get("pos", "0"))) > 0.000001
                ]

                if len(symbol_positions) > 0:
                    # Определяем направление сигнала и позиции
                    signal_side = side.lower()
                    signal_is_long = signal_side in ["buy", "long"]
                    signal_is_short = signal_side in ["sell", "short"]

                    pos_side = symbol_positions[0].get("posSide", "").lower()
                    if not pos_side or pos_side not in ["long", "short"]:
                        pos_size_raw = float(symbol_positions[0].get("pos", "0"))
                        pos_side = "long" if pos_size_raw > 0 else "short"

                    pos_is_long = pos_side == "long"
                    pos_is_short = pos_side == "short"

                    # Если сигнал в том же направлении - пропускаем
                    if (signal_is_long and pos_is_long) or (
                        signal_is_short and pos_is_short
                    ):
                        logger.debug(
                            f"⚠️ Позиция {symbol} {pos_side.upper()} уже открыта, "
                            f"сигнал в том же направлении - пропускаем"
                        )
                        return

                    # Если сигнал в противоположном направлении - закрываем старую и открываем новую
                    if (signal_is_long and pos_is_short) or (
                        signal_is_short and pos_is_long
                    ):
                        logger.info(
                            f"🔄 Сигнал {signal_side.upper()} для {symbol}, "
                            f"закрываем старую позицию {pos_side.upper()} перед открытием новой"
                        )
                        pos_to_close = symbol_positions[0]
                        pos_size = abs(float(pos_to_close.get("pos", "0")))
                        close_side = "sell" if pos_side == "long" else "buy"

                        close_result = await self.client.place_futures_order(
                            symbol=symbol,
                            side=close_side,
                            size=pos_size,
                            order_type="market",
                            reduce_only=True,
                            size_in_contracts=True,
                        )

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка на None перед использованием
                        if close_result is None:
                            logger.error(
                                f"❌ place_futures_order вернул None при закрытии позиции {symbol} {pos_side.upper()}"
                            )
                            return  # Не открываем новую позицию, если не удалось закрыть старую

                        if close_result.get("code") != "0":
                            logger.error(
                                f"❌ Не удалось закрыть позицию {symbol} {pos_side.upper()}: {close_result.get('msg', 'Неизвестная ошибка')}"
                            )
                            return  # Не открываем новую позицию, если не удалось закрыть старую

                        logger.info(
                            f"✅ Позиция {symbol} {pos_side.upper()} закрыта, открываем новую {signal_side.upper()}"
                        )
                        await asyncio.sleep(1)  # Даем время на закрытие

            except Exception as e:
                logger.debug(
                    f"⚠️ Не удалось проверить активную позицию для {symbol}: {e}"
                )

            # 🔥 КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем активные ордера перед размещением
            try:
                inst_id = f"{symbol}-SWAP"
                active_orders = await self.client.get_active_orders(symbol)
                open_position_orders = [
                    o
                    for o in active_orders
                    if o.get("instId") == inst_id
                    and o.get("side", "").lower() in ["buy", "sell"]
                    and o.get("reduceOnly", "false").lower() != "true"
                ]
                if len(open_position_orders) > 0:
                    logger.warning(
                        f"⚠️ Уже есть {len(open_position_orders)} активных ордеров для {symbol}, пропускаем"
                    )
                    return
            except Exception as e:
                logger.warning(f"⚠️ Ошибка проверки активных ордеров: {e}")
                return

            # ✅ НОВОЕ: Расчет размера позиции с использованием DataRegistry
            # Получаем баланс из DataRegistry
            balance = None
            if self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    balance = balance_data.get("balance") if balance_data else None
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка получения баланса из DataRegistry: {e}")

            # Fallback: если DataRegistry не доступен или нет данных
            if balance is None:
                balance = await self.client.get_balance()

            current_price = signal.get("price", 0)

            # ✅ НОВОЕ: Получаем режим из DataRegistry
            current_regime = None
            symbol = signal.get("symbol")
            if symbol and self.data_registry:
                try:
                    regime_data = await self.data_registry.get_regime(symbol)
                    if regime_data:
                        current_regime = regime_data.get("regime")
                        if current_regime:
                            current_regime = current_regime.lower()
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка получения режима из DataRegistry для {symbol}: {e}"
                    )

            # Fallback: если DataRegistry не доступен или нет данных
            if not current_regime:
                # ✅ НОВОЕ: Получаем режим из DataRegistry
                if symbol and self.data_registry:
                    try:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data:
                            current_regime = regime_data.get("regime")
                            if current_regime:
                                current_regime = current_regime.lower()
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка получения режима из DataRegistry для {symbol}: {e}"
                        )

                # Fallback: если DataRegistry не доступен или нет данных
                if not current_regime:
                    try:
                        if (
                            hasattr(self.signal_generator, "regime_manager")
                            and self.signal_generator
                        ):
                            regime_obj = (
                                self.signal_generator.regime_manager.get_current_regime()
                            )
                            if regime_obj:
                                current_regime = (
                                    regime_obj.lower()
                                    if isinstance(regime_obj, str)
                                    else str(regime_obj).lower()
                                )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить режим для расчета размера позиции: {e}"
                        )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем адаптивный risk_per_trade_percent из конфига по режиму
            # margin_calculator сам выберет правильный риск из конфига (risk_per_trade_percent из режима -> risk секции -> base_risk_percentage)
            risk_percentage = (
                None  # None - margin_calculator читает из конфига по режиму
            )

            position_size = self.margin_calculator.calculate_optimal_position_size(
                balance,
                current_price,
                risk_percentage,
                leverage=None,
                regime=current_regime,
                trading_statistics=self.trading_statistics
                if hasattr(self, "trading_statistics")
                else None,
            )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #2: Дополнительная проверка позиций перед открытием
            # Используем блокировку по символу для предотвращения race condition
            if symbol not in self.signal_locks_ref:
                self.signal_locks_ref[symbol] = asyncio.Lock()

            async with self.signal_locks_ref[symbol]:
                # Проверяем позиции еще раз непосредственно перед открытием
                try:
                    positions = await self.client.get_positions()
                    inst_id = f"{symbol}-SWAP"
                    symbol_positions = [
                        p
                        for p in positions
                        if (
                            p.get("instId", "") == inst_id
                            or p.get("instId", "") == symbol
                            or p.get("instId", "").replace("-", "")
                            == inst_id.replace("-", "")
                        )
                        and abs(float(p.get("pos", "0"))) > 0.000001
                    ]

                    if len(symbol_positions) > 0:
                        # Проверяем противоположные позиции
                        has_long = any(
                            p.get("posSide", "").lower() == "long"
                            or (
                                float(p.get("pos", "0")) > 0
                                and p.get("posSide", "").lower()
                                not in ["long", "short"]
                            )
                            for p in symbol_positions
                        )
                        has_short = any(
                            p.get("posSide", "").lower() == "short"
                            or (
                                float(p.get("pos", "0")) < 0
                                and p.get("posSide", "").lower()
                                not in ["long", "short"]
                            )
                            for p in symbol_positions
                        )

                        signal_side = side.lower()
                        signal_is_long = signal_side in ["buy", "long"]
                        signal_is_short = signal_side in ["sell", "short"]

                        # Если есть противоположные позиции - закрываем их
                        if has_long and has_short:
                            logger.warning(
                                f"🚨 Обнаружены противоположные позиции для {symbol} перед открытием, закрываем одну из них"
                            )
                            await self._close_opposite_position(
                                symbol, symbol_positions
                            )
                            # После закрытия проверяем еще раз
                            await asyncio.sleep(1)  # Даем время на закрытие
                            positions = await self.client.get_positions()
                            symbol_positions = [
                                p
                                for p in positions
                                if (
                                    p.get("instId", "") == inst_id
                                    or p.get("instId", "") == symbol
                                    or p.get("instId", "").replace("-", "")
                                    == inst_id.replace("-", "")
                                )
                                and abs(float(p.get("pos", "0"))) > 0.000001
                            ]

                        # Проверяем, есть ли позиция в том же направлении
                        if signal_is_long and has_long:
                            logger.warning(
                                f"⚠️ Позиция {symbol} LONG уже открыта перед открытием новой, пропускаем"
                            )
                            return
                        elif signal_is_short and has_short:
                            logger.warning(
                                f"⚠️ Позиция {symbol} SHORT уже открыта перед открытием новой, пропускаем"
                            )
                            return
                        elif (signal_is_long and has_short) or (
                            signal_is_short and has_long
                        ):
                            # Есть позиция в противоположном направлении - закрываем её перед открытием новой
                            logger.info(
                                f"🔄 Закрываем противоположную позицию {symbol} перед открытием новой"
                            )
                            pos_to_close = symbol_positions[0]
                            pos_side_to_close = pos_to_close.get("posSide", "").lower()
                            if not pos_side_to_close or pos_side_to_close not in [
                                "long",
                                "short",
                            ]:
                                pos_side_to_close = (
                                    "long"
                                    if float(pos_to_close.get("pos", "0")) > 0
                                    else "short"
                                )

                            close_side = (
                                "sell" if pos_side_to_close == "long" else "buy"
                            )
                            pos_size = abs(float(pos_to_close.get("pos", "0")))

                            close_result = await self.client.place_futures_order(
                                symbol=symbol,
                                side=close_side,
                                size=pos_size,
                                order_type="market",
                                reduce_only=True,
                                size_in_contracts=True,
                            )

                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка на None перед использованием
                            if close_result is None:
                                logger.error(
                                    f"❌ place_futures_order вернул None при закрытии противоположной позиции {symbol} {pos_side_to_close.upper()}"
                                )
                                return  # Не открываем новую позицию, если не удалось закрыть старую

                            if close_result.get("code") != "0":
                                logger.error(
                                    f"❌ Не удалось закрыть противоположную позицию {symbol} {pos_side_to_close.upper()}: {close_result.get('msg', 'Неизвестная ошибка')}"
                                )
                                return  # Не открываем новую позицию, если не удалось закрыть старую

                            logger.info(
                                f"✅ Противоположная позиция {symbol} {pos_side_to_close.upper()} закрыта, открываем новую"
                            )
                            await asyncio.sleep(1)  # Даем время на закрытие

                except Exception as e:
                    logger.warning(
                        f"⚠️ Ошибка дополнительной проверки позиций для {symbol} перед открытием: {e}"
                    )
                    # При ошибке лучше не открывать позицию
                    return

                # Исполнение ордера
                result = await self.order_executor.execute_signal(signal, position_size)

            if result.get("success"):
                logger.info(f"✅ Сигнал {symbol} {side} успешно исполнен")
            else:
                logger.error(
                    f"❌ Ошибка исполнения сигнала {symbol}: {result.get('error')}"
                )

        except Exception as e:
            logger.error(f"Ошибка исполнения сигнала: {e}")

    async def check_for_signals(self, symbol: str, price: float):
        """✅ РЕАЛЬНАЯ генерация сигналов на основе индикаторов"""
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Нормализуем символ для блокировки
            # Это предотвращает race condition при разных форматах ("BTC-USDT" vs "BTCUSDT")
            normalized_symbol = (
                self.normalize_symbol_callback(symbol)
                if self.normalize_symbol_callback
                else symbol
            )

            # ✅ FIX: Circuit breaker - проверяем блокировку символа (до блокировки)
            if self.risk_manager and self.risk_manager.is_symbol_blocked(symbol):
                logger.debug(f"SKIP_BLOCK {symbol}: blocked by consecutive losses")
                return

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: БЛОКИРОВКА для предотвращения race condition
            # Создаем блокировку для нормализованного символа, если её нет
            if normalized_symbol not in self.signal_locks_ref:
                self.signal_locks_ref[normalized_symbol] = asyncio.Lock()

            # Используем блокировку - только один поток может обрабатывать сигнал для символа одновременно
            async with self.signal_locks_ref[normalized_symbol]:
                # ✅ ИСПРАВЛЕНИЕ: Убираем проверку "если позиция уже есть по символу"
                # Теперь разрешаем несколько позиций по одному символу (например, 3 на BTC и 3 на ETH)
                # Проверяем только общий лимит позиций

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Определяем current_time в начале блока
                current_time = time.time()

                # ✅ ЭТАП 3.4: УБРАН cooldown между сигналами для увеличения частоты сделок
                # Проверка задержки между сигналами удалена - теперь сигналы генерируются без задержки
                # Это позволяет боту работать в режиме высокочастотного скальпинга (80-120 сделок/час)

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка последнего ордера через кэш (используем нормализованный символ)
                if normalized_symbol in self.last_orders_cache_ref:
                    last_order = self.last_orders_cache_ref[normalized_symbol]
                    order_time = last_order.get("timestamp", 0)
                    order_status = last_order.get("status", "unknown")
                    # ✅ УСИЛЕНО: Если ордер был размещен менее 15 секунд назад и pending - строго блокируем
                    # Это предотвращает двойные ордера из-за задержки API
                    time_since_order = current_time - order_time
                    if time_since_order < 15 and order_status == "pending":
                        logger.warning(
                            f"⚠️ Ордер для {symbol} был размещен {time_since_order:.1f}s назад (status=pending), "
                            f"строго блокируем новый ордер (предотвращение двойных ордеров)"
                        )
                        return
                    # Если последний ордер был недавно (менее 30 секунд) и не был отменен/исполнен - пропускаем
                    if time_since_order < 30 and order_status not in [
                        "filled",
                        "cancelled",
                        "rejected",
                    ]:
                        logger.debug(
                            f"⏱️ Последний ордер для {symbol} был недавно ({current_time - order_time:.1f}s назад), "
                            f"статус: {order_status}, пропускаем новый сигнал"
                        )
                        return

                # 🔥 КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем активные ордера ПЕРЕД генерацией сигнала
                # Используем кэш для оптимизации (проверяем не чаще раза в 5 секунд)
                inst_id = f"{symbol}-SWAP"
                should_check_orders = True
                if normalized_symbol in self.last_orders_check_time_ref:
                    time_since_check = (
                        current_time
                        - self.last_orders_check_time_ref[normalized_symbol]
                    )
                    if time_since_check < 5:  # Проверяем не чаще раза в 5 секунд
                        # Используем кэш (с нормализованным символом)
                        if normalized_symbol in self.active_orders_cache_ref:
                            cached_orders = self.active_orders_cache_ref[
                                normalized_symbol
                            ]
                            if cached_orders.get("order_ids"):
                                logger.debug(
                                    f"📦 Используем кэш активных ордеров для {symbol}: {len(cached_orders['order_ids'])} ордеров"
                                )
                                if len(cached_orders["order_ids"]) > 0:
                                    logger.warning(
                                        f"⚠️ В кэше есть {len(cached_orders['order_ids'])} активных ордеров для {symbol}, "
                                        f"пропускаем генерацию нового сигнала"
                                    )
                                    return
                                should_check_orders = False

                if should_check_orders:
                    try:
                        active_orders = await self.client.get_active_orders(symbol)
                        # Считаем только ордера на открытие позиции (не reduceOnly)
                        open_position_orders = [
                            o
                            for o in active_orders
                            if o.get("instId") == inst_id
                            and o.get("side", "").lower() in ["buy", "sell"]
                            and o.get("reduceOnly", "false").lower() != "true"
                        ]

                        # Обновляем кэш (с нормализованным символом)
                        self.active_orders_cache_ref[normalized_symbol] = {
                            "order_ids": [o.get("ordId") for o in open_position_orders],
                            "timestamp": current_time,
                        }
                        self.last_orders_check_time_ref[
                            normalized_symbol
                        ] = current_time

                        if len(open_position_orders) > 0:
                            logger.warning(
                                f"⚠️ Уже есть {len(open_position_orders)} активных ордеров на открытие позиции {symbol}, "
                                f"пропускаем генерацию нового сигнала"
                            )
                            return
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка проверки активных ордеров для {symbol}: {e}"
                        )
                        # Если не можем проверить - лучше пропустить, чем создать дубликат
                        return

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сначала проверяем active_positions_ref для быстрой проверки
                # Это предотвращает race condition и множественные запросы к бирже
                has_position_in_cache = False
                if self.active_positions_ref and symbol in self.active_positions_ref:
                    cached_pos = self.active_positions_ref.get(symbol, {})
                    cached_size = cached_pos.get("size", 0)
                    if cached_size and abs(float(cached_size)) > 0.000001:
                        has_position_in_cache = True
                        cached_side = cached_pos.get("position_side", "").lower()
                        logger.debug(
                            f"🔍 Найдена позиция {symbol} в кэше: size={cached_size}, side={cached_side}"
                        )

                # 🔥 СКАЛЬПИНГ: Проверяем реальные позиции на бирже перед открытием новых
                # ✅ КРИТИЧЕСКОЕ: Проверяем ТОЛЬКО если нет позиции в кэше (оптимизация)
                try:
                    all_positions = await self.client.get_positions()
                    active_positions_count = len(
                        [p for p in all_positions if float(p.get("pos", "0")) != 0]
                    )

                    # ✅ ИСПРАВЛЕНИЕ: Проверяем позиции по нескольким вариантам instId
                    # instId может быть в форматах: "ETH-USDT-SWAP", "ETH-USDT", "ETHUSDT-SWAP"
                    symbol_positions = []
                    for p in all_positions:
                        pos_inst_id = p.get("instId", "")
                        pos_size = abs(float(p.get("pos", "0")))

                        # Проверяем все возможные форматы
                        if pos_size > 0.000001:
                            # Формат "-SWAP" (стандартный)
                            if pos_inst_id == inst_id:
                                symbol_positions.append(p)
                            # Формат без "-SWAP" (если API вернул без суффикса)
                            elif pos_inst_id == symbol:
                                symbol_positions.append(p)
                            # Формат с другим разделителем
                            elif pos_inst_id.replace("-", "") == inst_id.replace(
                                "-", ""
                            ):
                                symbol_positions.append(p)

                    # ✅ КРИТИЧЕСКОЕ: Если позиция есть в кэше, но не на бирже - очищаем кэш
                    if has_position_in_cache and len(symbol_positions) == 0:
                        logger.warning(
                            f"⚠️ Позиция {symbol} была в кэше, но отсутствует на бирже, очищаем кэш"
                        )
                        if symbol in self.active_positions_ref:
                            self.active_positions_ref.pop(symbol)
                        if symbol in self.max_size_limiter.position_sizes:
                            self.max_size_limiter.remove_position(symbol)

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем направление позиции!
                    # На OKX Futures несколько ордеров в ОДНОМ направлении объединяются в ОДНУ позицию
                    # Поэтому нужно блокировать новые ордера, если уже есть позиция в этом направлении
                    allow_concurrent = getattr(
                        self.scalping_config, "allow_concurrent_positions", False
                    )

                    # Получаем направление сигнала из генератора сигналов
                    # Нужно определить направление сигнала здесь - но в check_for_signals мы еще не знаем направление
                    # Поэтому проверяем все позиции и блокируем, если есть позиция в любом направлении
                    # (проверка направления будет в process_signals)

                    if len(symbol_positions) > 0:
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем направление позиции!
                        # На OKX Futures в hedge mode могут быть LONG и SHORT позиции одновременно
                        # Но мы блокируем только если есть позиция в ТОМ ЖЕ направлении, что и сигнал
                        # Направление сигнала мы узнаем только после генерации, поэтому здесь блокируем ВСЕ позиции
                        # если allow_concurrent=false, иначе разрешаем противоположные
                        positions_info = [
                            f"{p.get('instId')}: {p.get('pos')} (posSide={p.get('posSide', 'N/A')})"
                            for p in symbol_positions
                        ]

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Если allow_concurrent=false, проверяем противоположные позиции
                        if not allow_concurrent:
                            # Проверяем, есть ли противоположные позиции (LONG и SHORT одновременно)
                            has_long = any(
                                p.get("posSide", "").lower() == "long"
                                or (
                                    float(p.get("pos", "0")) > 0
                                    and p.get("posSide", "").lower()
                                    not in ["long", "short"]
                                )
                                for p in symbol_positions
                            )
                            has_short = any(
                                p.get("posSide", "").lower() == "short"
                                or (
                                    float(p.get("pos", "0")) < 0
                                    and p.get("posSide", "").lower()
                                    not in ["long", "short"]
                                )
                                for p in symbol_positions
                            )

                            # ✅ НОВОЕ: Разрешаем LONG и SHORT одновременно, разрешаем суммирование ордеров
                            # Подсчитываем ордера в том же направлении что и сигнал
                            signal_position_side = signal.get(
                                "position_side", "long"
                            ).lower()
                            same_direction_count = 0
                            for pos in symbol_positions:
                                pos_side_raw = pos.get("posSide", "").lower()
                                pos_raw = float(pos.get("pos", "0"))
                                if pos_side_raw in ["long", "short"]:
                                    pos_side = pos_side_raw
                                else:
                                    pos_side = "long" if pos_raw > 0 else "short"

                                if pos_side == signal_position_side:
                                    same_direction_count += 1

                            # Если уже 5 ордеров в том же направлении → полное закрытие позиции
                            if same_direction_count >= 5:
                                logger.info(
                                    f"🔄 {symbol}: Достигнут лимит 5 ордеров в направлении {signal_position_side.upper()}, "
                                    f"закрываем все позиции перед новым сигналом"
                                )
                                # Закрываем все позиции по символу
                                if hasattr(self, "orchestrator") and self.orchestrator:
                                    if hasattr(self.orchestrator, "position_manager"):
                                        await self.orchestrator.position_manager.close_position_manually(
                                            symbol, reason="max_orders_reached"
                                        )
                                # Продолжаем открытие новой позиции после закрытия
                            elif same_direction_count > 0:
                                logger.debug(
                                    f"📊 {symbol}: Уже есть {same_direction_count} ордер(ов) в направлении {signal_position_side.upper()}, "
                                    f"разрешаем суммирование (до 5)"
                                )
                                # Разрешаем открытие - ордера суммируются

                            # Разрешаем LONG и SHORT одновременно - бот сам закроет когда увидит разворот
                            if has_long and has_short:
                                logger.debug(
                                    f"📊 {symbol}: Есть LONG и SHORT одновременно - разрешаем (хеджирование)"
                                )
                                # Разрешаем - бот сам закроет когда увидит разворот
                        # Проверка направления завершена - разрешаем открытие

                    # ✅ НОВОЕ: Получаем баланс и режим из DataRegistry
                    balance = None
                    if self.data_registry:
                        try:
                            balance_data = await self.data_registry.get_balance()
                            balance = (
                                balance_data.get("balance") if balance_data else None
                            )
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Ошибка получения баланса из DataRegistry: {e}"
                            )

                    # Fallback: если DataRegistry не доступен или нет данных
                    if balance is None:
                        balance = await self.client.get_balance()

                    balance_profile = self.config_manager.get_balance_profile(balance)
                    max_open = balance_profile.get(
                        "max_open_positions", 6
                    )  # ✅ Увеличено до 6 (3 на BTC + 3 на ETH)

                    if active_positions_count >= max_open:
                        logger.debug(
                            f"⚠️ Достигнут лимит открытых позиций на бирже: {active_positions_count}/{max_open}. "
                            f"Пропускаем открытие {symbol}"
                        )
                        return

                    # 🔥 СКАЛЬПИНГ: Проверяем реальный баланс на бирже
                    # get_balance() возвращает equity (общий баланс с учетом PnL)
                    # ✅ МОДЕРНИЗАЦИЯ: Используем адаптивный min_balance_usd из конфига
                    # ✅ НОВОЕ: Получаем режим из DataRegistry
                    regime = None
                    if self.data_registry:
                        try:
                            regime_data = await self.data_registry.get_regime(symbol)
                            if regime_data:
                                regime = regime_data.get("regime")
                        except Exception as e:
                            logger.debug(
                                f"⚠️ Ошибка получения режима из DataRegistry для {symbol}: {e}"
                            )

                    # Fallback: если DataRegistry не доступен или нет данных
                    if not regime:
                        if (
                            hasattr(self.signal_generator, "regime_manager")
                            and self.signal_generator.regime_manager
                        ):
                            regime = (
                                self.signal_generator.regime_manager.get_current_regime()
                            )
                    # ✅ ИСПРАВЛЕНО (26.12.2025): Используем ParameterProvider для получения risk_params
                    if self.parameter_provider:
                        adaptive_risk_params = self.parameter_provider.get_risk_params(
                            symbol, balance, regime
                        )
                    else:
                        adaptive_risk_params = self.config_manager.get_adaptive_risk_params(
                            balance, regime, signal_generator=self.signal_generator
                        )
                    min_balance_usd = adaptive_risk_params.get("min_balance_usd", 20.0)

                    if balance < min_balance_usd:
                        logger.debug(
                            f"⚠️ Недостаточно баланса на бирже: ${balance:.2f} < ${min_balance_usd:.2f}. "
                            f"Пропускаем открытие {symbol}"
                        )
                        return

                except Exception as e:
                    logger.warning(f"⚠️ Ошибка проверки лимита позиций: {e}")

                # ✅ РЕАЛЬНАЯ ГЕНЕРАЦИЯ СИГНАЛОВ через signal_generator
                # Используем реальные индикаторы, а не тестовую логику!
                try:
                    # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование (есть INFO логи)
                    # logger.debug(f"🔍 Генерация сигналов для {symbol}...")

                    # ✅ Получаем текущие позиции для CorrelationFilter
                    try:
                        all_positions = await self.client.get_positions()
                        # Конвертируем в формат для CorrelationFilter
                        current_positions_dict = {}
                        for pos in all_positions:
                            pos_size = float(pos.get("pos", "0"))
                            if pos_size != 0:
                                inst_id_pos = pos.get("instId", "")
                                # ✅ ИСПРАВЛЕНИЕ: Убираем только -SWAP, оставляем -USDT (формат "BTC-USDT")
                                symbol_key = inst_id_pos.replace("-SWAP", "")
                                current_positions_dict[symbol_key] = pos
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить позиции для CorrelationFilter: {e}"
                        )
                        current_positions_dict = {}

                    # Генерируем сигналы для всех символов (система сама отфильтрует по symbol)
                    # Передаем позиции в signal_generator для CorrelationFilter
                    signals = await self.signal_generator.generate_signals(
                        current_positions=current_positions_dict
                    )

                    # ✅ ДОБАВЛЕНО: Логирование для отладки
                    if len(signals) > 0:
                        logger.info(f"📊 check_for_signals {symbol}: Сгенерировано {len(signals)} сигналов")
                    else:
                        logger.debug(f"📊 check_for_signals {symbol}: Сигналов не сгенерировано")

                    # Ищем сигнал для текущего символа
                    symbol_signal = None
                    filtered_reasons = []  # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ (25.12.2025): Собираем причины отфильтровывания
                    for signal in signals:
                        if signal.get("symbol") == symbol:
                            symbol_signal = signal
                            break
                    
                    # ✅ НОВОЕ (27.12.2025): Детальное логирование отсутствия сигналов
                    if symbol_signal is None:
                        # Проверяем, были ли вообще сигналы сгенерированы
                        if len(signals) == 0:
                            # Получаем детальную информацию о причинах отсутствия сигналов
                            try:
                                # Пробуем получить данные для анализа
                                market_data = await self.signal_generator._get_market_data(symbol)
                                if market_data:
                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Берем ADX из DataRegistry, а не из market_data.indicators
                                    # market_data.indicators не содержит ADX, он хранится отдельно в DataRegistry
                                    adx_value = 0.0
                                    adx_trend = "unknown"
                                    rsi = 50.0
                                    
                                    # Пытаемся получить ADX из DataRegistry
                                    if self.data_registry:
                                        try:
                                            indicators_from_registry = await self.data_registry.get_indicators(symbol)
                                            if indicators_from_registry:
                                                adx_from_reg = indicators_from_registry.get("adx")
                                                if adx_from_reg and isinstance(adx_from_reg, (int, float)) and float(adx_from_reg) > 0:
                                                    adx_value = float(adx_from_reg)
                                                    adx_plus_di = indicators_from_registry.get("adx_plus_di", 0)
                                                    adx_minus_di = indicators_from_registry.get("adx_minus_di", 0)
                                                    
                                                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен порог ADX с 25 до 20
                                                    # Определяем тренд
                                                    if adx_value >= 20.0:
                                                        if adx_plus_di > adx_minus_di + 5.0:
                                                            adx_trend = "bullish"
                                                        elif adx_minus_di > adx_plus_di + 5.0:
                                                            adx_trend = "bearish"
                                                        else:
                                                            adx_trend = "ranging"
                                                    else:
                                                        adx_trend = "ranging"
                                        except Exception as e:
                                            logger.debug(f"⚠️ Не удалось получить ADX из DataRegistry для {symbol}: {e}")
                                    
                                    # Если ADX не получили из DataRegistry, берем из market_data.indicators (fallback)
                                    if adx_value == 0.0:
                                        indicators = market_data.indicators if hasattr(market_data, "indicators") else {}
                                        adx_value = indicators.get("adx", indicators.get("adx_proxy", 0))
                                        rsi = indicators.get("rsi", 50)
                                        
                                        # Пытаемся определить тренд через adx_filter (fallback)
                                        try:
                                            if self.signal_generator.adx_filter and market_data.ohlcv_data:
                                                candles_dict = []
                                                for candle in market_data.ohlcv_data:
                                                    candles_dict.append({
                                                        "high": candle.high,
                                                        "low": candle.low,
                                                        "close": candle.close,
                                                    })
                                                from src.strategies.modules.adx_filter import OrderSide
                                                buy_result = self.signal_generator.adx_filter.check_trend_strength(
                                                    symbol, OrderSide.BUY, candles_dict
                                                )
                                                adx_value_check = buy_result.adx_value
                                                adx_plus_di = buy_result.plus_di
                                                adx_minus_di = buy_result.minus_di
                                                
                                                if adx_value_check > 0:
                                                    adx_value = adx_value_check
                                                
                                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Снижен порог ADX с 25 до 20
                                                if adx_value >= 20.0:
                                                    if adx_plus_di > adx_minus_di + 5.0:
                                                        adx_trend = "bullish"
                                                    elif adx_minus_di > adx_plus_di + 5.0:
                                                        adx_trend = "bearish"
                                                    else:
                                                        adx_trend = "ranging"
                                                else:
                                                    adx_trend = "ranging"
                                        except Exception:
                                            pass
                                    else:
                                        # Если ADX получен из DataRegistry, берем RSI из indicators
                                        indicators = market_data.indicators if hasattr(market_data, "indicators") else {}
                                        rsi = indicators.get("rsi", 50)
                                    
                                    logger.warning(
                                        f"🚫 НЕТ СИГНАЛОВ: {symbol} - signal_generator.generate_signals() вернул 0 сигналов. "
                                        f"Причины: ADX={adx_value:.1f} ({adx_trend}), RSI={rsi:.1f}, "
                                        f"возможные причины: все фильтры заблокировали, нет подходящих условий, режим рынка"
                                    )
                                else:
                                    logger.warning(
                                        f"🚫 НЕТ СИГНАЛОВ: {symbol} - signal_generator.generate_signals() вернул 0 сигналов "
                                        f"(не удалось получить market_data для анализа)"
                                    )
                            except Exception as e:
                                logger.warning(
                                    f"🚫 НЕТ СИГНАЛОВ: {symbol} - signal_generator.generate_signals() вернул 0 сигналов "
                                    f"(возможные причины: все фильтры заблокировали, нет подходящих условий, режим рынка). "
                                    f"Ошибка анализа: {e}"
                                )
                        else:
                            # Сигналы есть, но не для этого символа
                            logger.debug(
                                f"🔍 НЕТ СИГНАЛА ДЛЯ СИМВОЛА: {symbol} - сгенерировано {len(signals)} сигналов для других символов"
                            )

                    # ✅ FIX: Positive EV filter — проверяем математическое ожидание
                    if symbol_signal:
                        atr_14 = symbol_signal.get("atr", 0)
                        regime = symbol_signal.get("regime", "ranging")
                        entry_price = symbol_signal.get("price", price)

                        if atr_14 > 0 and entry_price > 0:
                            # Получаем SL-множитель для расчёта ожидаемого движения
                            sl_mult = 0.5  # Default
                            # ✅ НОВОЕ (26.12.2025): Используем ParameterProvider вместо прямого обращения к config_manager
                            if hasattr(self, "parameter_provider") and self.parameter_provider:
                                try:
                                    regime_params = self.parameter_provider.get_regime_params(
                                        symbol=symbol,
                                        regime=regime
                                    )
                                    if regime_params:
                                        sl_mult = regime_params.get(
                                            "sl_atr_multiplier", 0.5
                                        )
                                except Exception:
                                    pass
                            elif hasattr(self, "config_manager") and self.config_manager:
                                # Fallback на config_manager
                                try:
                                    regime_params = (
                                        self.config_manager.get_regime_params(regime)
                                    )
                                    if regime_params:
                                        sl_mult = regime_params.get(
                                            "sl_atr_multiplier", 0.5
                                        )
                                except Exception:
                                    pass

                            expected_move = (
                                atr_14 / entry_price
                            ) * sl_mult  # % движение

                            # Считаем затраты: maker + taker + slippage buffer
                            maker_fee = 0.0002  # 0.02%
                            taker_fee = 0.0005  # 0.05%
                            slippage_buffer = 0.0005  # 0.05%
                            if (
                                hasattr(self, "scalping_config")
                                and self.scalping_config
                            ):
                                comm = getattr(self.scalping_config, "commission", None)
                                if comm:
                                    maker_fee = (
                                        getattr(comm, "maker_fee_rate", 0.0002)
                                        or 0.0002
                                    )
                                    taker_fee = (
                                        getattr(comm, "taker_fee_rate", 0.0005)
                                        or 0.0005
                                    )

                            total_cost = maker_fee + taker_fee + slippage_buffer

                            if expected_move < total_cost:
                                filtered_reasons.append(
                                    f"EV_NEGATIVE (expected_move={expected_move:.4f}% < cost={total_cost:.4f}%)"
                                )
                                logger.debug(
                                    f"🔍 [SIGNAL_FILTER] {symbol}: EV_NEGATIVE - move={expected_move:.4f}% < cost={total_cost:.4f}%"
                                )
                                symbol_signal = None  # Отменяем сигнал

                    # Если нашли реальный сигнал - выполняем его
                    if symbol_signal:
                        side = symbol_signal.get("side")
                        strength = symbol_signal.get("strength", 0)
                        side_str = "LONG" if side == "buy" else "SHORT"

                        logger.info(
                            f"🎯 РЕАЛЬНЫЙ СИГНАЛ {symbol} {side_str} @ ${price:.2f} "
                            f"(сила={strength:.2f})"
                        )

                        # ✅ ЭТАП 3.4: УБРАНО обновление времени последнего сигнала (cooldown удален)

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Дополнительная проверка перед выполнением
                        # Проверяем, не был ли уже размещен ордер за последние 2 секунды (с нормализованным символом)
                        if normalized_symbol in self.last_orders_cache_ref:
                            last_order = self.last_orders_cache_ref[normalized_symbol]
                            order_time = last_order.get("timestamp", 0)
                            if (current_time - order_time) < 2:
                                logger.warning(
                                    f"⚠️ Ордер для {symbol} был размещен {current_time - order_time:.1f}s назад, "
                                    f"пропускаем выполнение сигнала (блокировка внутри lock)"
                                )
                                return

                        # Выполняем реальный сигнал
                        success = await self.execute_signal_from_price(
                            symbol, price, symbol_signal
                        )
                        if success:
                            logger.info(
                                f"✅ Позиция {symbol} {side_str} открыта по реальному сигналу"
                            )
                        else:
                            logger.warning(
                                f"⚠️ Не удалось открыть позицию {symbol} {side_str} (недостаточно маржи или другие ограничения)"
                            )
                    else:
                        # ✅ ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ (25.12.2025): Логируем причины отсутствия сигналов
                        if filtered_reasons:
                            logger.info(
                                f"📊 {symbol}: Сигнал отфильтрован. Причины: {', '.join(filtered_reasons)}. "
                                f"Всего сгенерировано: {len(signals)} сигналов."
                            )
                            # ✅ НОВОЕ (26.12.2025): Записываем отфильтрованные сигналы в метрики
                            if hasattr(self, 'conversion_metrics') and self.conversion_metrics:
                                try:
                                    # Получаем режим для метрики
                                    regime = None
                                    if hasattr(self.signal_generator, "regime_managers"):
                                        regime_manager = self.signal_generator.regime_managers.get(symbol)
                                        if regime_manager:
                                            regime_obj = regime_manager.get_current_regime()
                                            if regime_obj:
                                                regime = str(regime_obj).lower() if not hasattr(regime_obj, 'value') else regime_obj.value.lower()
                                    
                                    # Записываем каждую причину фильтрации
                                    for reason in filtered_reasons:
                                        self.conversion_metrics.record_signal_filtered(
                                            symbol=symbol,
                                            reason=reason,
                                            signal_type="unknown",
                                            regime=regime
                                        )
                                except Exception as e:
                                    logger.debug(f"⚠️ Ошибка записи метрики фильтрации для {symbol}: {e}")
                        else:
                            # ✅ Изменено на INFO для видимости - важно знать что сигналов нет
                            logger.info(
                                f"📊 {symbol}: сигналов нет (индикаторы не дают сигнала). "
                                f"Всего сгенерировано: {len(signals)} сигналов."
                            )

                except Exception as e:
                    logger.error(
                        f"❌ Ошибка генерации реальных сигналов для {symbol}: {e}",
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(f"❌ Ошибка проверки сигналов: {e}")

    async def execute_signal_from_price(
        self, symbol: str, price: float, signal=None
    ) -> bool:
        """Выполняет торговый сигнал на основе цены. Возвращает True если позиция успешно открыта."""
        try:
            # 🔥 КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем РЕАЛЬНЫЕ позиции на бирже ПЕРЕД открытием новой
            # Это предотвращает дубликаты даже при race condition или перезапуске бота
            try:
                inst_id = f"{symbol}-SWAP"
                # Получаем направление сигнала
                signal_side = signal.get("side", "").lower() if signal else "buy"
                signal_position_side = "long" if signal_side == "buy" else "short"

                # Проверяем все позиции (не только по символу, чтобы увидеть все)
                all_positions = await self.client.get_positions()
                for pos in all_positions:
                    pos_size = float(pos.get("pos", "0"))
                    pos_inst_id = pos.get("instId", "")

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем все возможные форматы instId
                    # instId может быть: "BTC-USDT-SWAP", "BTCUSDT-SWAP", "BTC-USDT" и т.д.
                    if (
                        abs(pos_size) > 0.000001
                    ):  # Учитываем даже очень маленькие позиции
                        # Нормализуем оба instId (убираем разделители и приводим к одному формату)
                        normalized_pos_id = pos_inst_id.replace("-", "").upper()
                        normalized_inst_id = inst_id.replace("-", "").upper()

                        # Проверяем совпадение символа
                        if (
                            normalized_pos_id == normalized_inst_id
                            or pos_inst_id == inst_id
                        ):
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем направление позиции!
                            # На OKX Futures в hedge mode могут быть LONG и SHORT позиции одновременно
                            # Блокируем только если позиция в ТОМ ЖЕ направлении, что и сигнал
                            pos_side_raw = pos.get("posSide", "").lower()
                            if pos_side_raw in ["long", "short"]:
                                actual_side = pos_side_raw
                            else:
                                actual_side = "long" if pos_size > 0 else "short"

                            # Проверяем allow_concurrent из конфига
                            allow_concurrent = getattr(
                                self.scalping_config,
                                "allow_concurrent_positions",
                                False,
                            )

                            if actual_side == signal_position_side:
                                # Позиция в том же направлении - блокируем
                                # ✅ ЛОГИРОВАНИЕ: Показываем, было ли переключение направления ADX
                                original_side = signal.get("original_side", "")
                                side_switched = signal.get(
                                    "side_switched_by_adx", False
                                )
                                if side_switched and original_side:
                                    original_position_side = (
                                        "long"
                                        if original_side.lower() == "buy"
                                        else "short"
                                    )
                                    logger.warning(
                                        f"⚠️ Позиция {symbol} {actual_side.upper()} уже открыта на бирже (size={abs(pos_size)}, instId={pos_inst_id}), "
                                        f"БЛОКИРУЕМ новый {signal_side.upper()} ордер "
                                        f"(ADX переключил направление с {original_position_side.upper()} → {signal_position_side.upper()}, "
                                        f"но позиция уже открыта в этом направлении)"
                                    )
                                else:
                                    logger.warning(
                                        f"⚠️ Позиция {symbol} {actual_side.upper()} уже открыта на бирже (size={abs(pos_size)}, instId={pos_inst_id}), "
                                        f"БЛОКИРУЕМ новый {signal_side.upper()} ордер (позиция в том же направлении)"
                                    )
                                return False
                            elif not allow_concurrent:
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #2: Позиция в другом направлении, allow_concurrent=false - БЛОКИРУЕМ открытие новой
                                logger.warning(
                                    f"🚨 Позиция {symbol} {actual_side.upper()} уже открыта на бирже (size={abs(pos_size)}, instId={pos_inst_id}), "
                                    f"БЛОКИРУЕМ открытие {signal_side.upper()} (allow_concurrent=false). "
                                    f"Позиция будет закрыта по TP/SL или вручную."
                                )
                                return False  # ✅ КРИТИЧЕСКОЕ: Блокируем открытие новой позиции, не закрываем автоматически
                            # Если allow_concurrent=true и позиция в другом направлении - разрешаем

                # 🔥 ДОПОЛНИТЕЛЬНО: Проверяем активные ордера на открытие позиции
                # Если есть pending ордер - тоже не открываем дубликат
                active_orders = await self.client.get_active_orders(symbol)
                for order in active_orders:
                    order_inst_id = order.get("instId", "")
                    order_side = order.get("side", "").lower()

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем все возможные форматы instId
                    normalized_order_id = order_inst_id.replace("-", "").upper()
                    normalized_inst_id = inst_id.replace("-", "").upper()

                    # Если есть активный ордер на открытие позиции (не закрытие) - пропускаем
                    if (
                        normalized_order_id == normalized_inst_id
                        or order_inst_id == inst_id
                    ) and order_side in ["buy", "sell"]:
                        # Проверяем, что это не ордер на закрытие (reduceOnly)
                        is_reduce_only = (
                            order.get("reduceOnly", "false").lower() == "true"
                        )
                        if not is_reduce_only:
                            logger.warning(
                                f"⚠️ Уже есть активный ордер на открытие позиции {symbol} (ordId={order.get('ordId', 'N/A')}, instId={order_inst_id}), "
                                f"пропускаем открытие дубликата"
                            )
                            return False
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка проверки позиций/ордеров на бирже для {symbol}: {e}"
                )
                # Если не удалось проверить - лучше пропустить, чем открыть дубликат
                # СТРОГАЯ ПРОВЕРКА: если не можем проверить - не открываем
                return False

            # Дополнительная проверка внутреннего счетчика (быстрая, но может быть неактуальной)
            if (
                symbol in self.active_positions_ref
                and "order_id" in self.active_positions_ref[symbol]
            ):
                logger.debug(f"Позиция {symbol} уже в активных, пропускаем")
                return False

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Проверка устаревания сигнала по времени (TTL 1 сек) и цене (>0.5%)
            if signal and signal.get("price"):
                signal_price = signal.get("price", 0.0)
                signal_timestamp = signal.get("timestamp")
                should_update_price = False
                update_reason = ""
                
                try:
                    current_price = 0  # Инициализируем для использования ниже
                    
                    # ✅ Проверка 1: Время устаревания (TTL 0.5 секунды)
                    if signal_timestamp:
                        if isinstance(signal_timestamp, datetime):
                            # Убеждаемся, что оба datetime имеют timezone
                            now_utc = datetime.now(timezone.utc)
                            if signal_timestamp.tzinfo is None:
                                # Если timestamp без timezone, считаем его UTC
                                signal_timestamp_utc = signal_timestamp.replace(tzinfo=timezone.utc)
                            else:
                                signal_timestamp_utc = signal_timestamp.astimezone(timezone.utc)
                            
                            time_diff = (now_utc - signal_timestamp_utc).total_seconds()
                            if time_diff > 0.5:  # TTL: 0.5 секунды (учитываем задержки)
                                should_update_price = True
                                update_reason = f"TTL истек (прошло {time_diff:.2f}с > 0.5с)"
                    
                    # ✅ Проверка 2: Разница цены (>0.5%)
                    price_limits = await self.order_executor.client.get_price_limits(symbol)
                    if price_limits:
                        current_price = price_limits.get("current_price", 0)
                        if current_price > 0 and signal_price > 0:
                            price_diff_pct = abs(signal_price - current_price) / current_price * 100
                            if price_diff_pct > 0.5:  # Разница > 0.5% - сигнал устарел
                                should_update_price = True
                                update_reason = f"разница цены {price_diff_pct:.2f}% > 0.5%"
                    
                    # ✅ Обновляем цену сигнала если устарел
                    if should_update_price and current_price > 0:
                        old_price = signal_price
                        signal["price"] = current_price
                        # Обновляем timestamp на текущее время
                        signal["timestamp"] = datetime.now(timezone.utc)
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Детальное логирование устаревания сигнала
                        time_info = ""
                        if signal_timestamp and isinstance(signal_timestamp, datetime):
                            now_utc = datetime.now(timezone.utc)
                            if signal_timestamp.tzinfo is None:
                                signal_timestamp_utc = signal_timestamp.replace(tzinfo=timezone.utc)
                            else:
                                signal_timestamp_utc = signal_timestamp.astimezone(timezone.utc)
                            time_diff = (now_utc - signal_timestamp_utc).total_seconds()
                            time_info = f", signal_age={time_diff:.2f}с"
                        
                        logger.warning(
                            f"⚠️ УСТАРЕВАНИЕ сигнала {symbol}: цена обновлена {old_price:.2f} → {current_price:.2f} ({update_reason}){time_info}"
                        )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка проверки актуальности signal['price'] для {symbol}: {e}"
                    )

            # Используем переданный сигнал или создаем тестовый
            if signal is None:
                # ✅ НОВОЕ: Определяем режим из DataRegistry (если ARM активен)
                regime = "ranging"  # По умолчанию

                # Получаем режим из DataRegistry
                if symbol and self.data_registry:
                    try:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data:
                            regime = regime_data.get("regime", "ranging")
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка получения режима из DataRegistry для {symbol}: {e}"
                        )

                # Fallback: если DataRegistry не доступен или нет данных
                if not regime or regime == "ranging":
                    if (
                        hasattr(self.signal_generator, "regime_manager")
                        and self.signal_generator.regime_manager
                    ):
                        try:
                            regime = (
                                self.signal_generator.regime_manager.get_current_regime()
                            )
                        except Exception as e:
                            logger.debug(f"Не удалось получить режим: {e}")
                            regime = None

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем РЫНОЧНЫЕ ордера (Market) для мгновенного исполнения
                # Лимитные ордера могут оставаться в pending и не открывать позиции
                # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: Используем limit ордера для экономии комиссий
                # Limit ордера дешевле в 2.5 раза (0.02% vs 0.05%), экономия $126/месяц при 180-200 сделках/день
                # Если limit ордер не исполнится - следующий сигнал, это нормально для скальпинга
                order_type = (
                    "limit"  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий
                )

                # Проверяем конфиг, можно ли переопределить
                try:
                    if hasattr(self.config, "scalping") and self.config.scalping:
                        scalping_config = self.config.scalping
                        if hasattr(scalping_config, "order_type"):
                            order_type = getattr(
                                scalping_config, "order_type", "limit"
                            )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" по умолчанию
                        elif hasattr(scalping_config, "prefer_market_orders"):
                            if getattr(scalping_config, "prefer_market_orders", False):
                                order_type = "market"
                except Exception as e:
                    logger.debug(
                        f"Не удалось получить тип ордера из конфига: {e}, используем limit (экономия комиссий)"
                    )

                signal = {
                    "symbol": symbol,
                    "side": "buy",
                    "price": price,
                    "strength": 0.8,
                    "regime": regime,  # ✅ Добавляем режим для адаптивных TP/SL
                    "type": order_type,  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: Limit ордера для экономии комиссий
                }

            # ✅ ИСПРАВЛЕНИЕ #3: Используем адаптивный леверидж на основе качества сигнала
            # Получаем режим и волатильность для расчета адаптивного левериджа
            # ✅ ИСПРАВЛЕНО (25.12.2025): Получаем режим с альтернативными источниками
            regime = signal.get("regime")
            if not regime:
                # Пробуем получить из signal_generator
                if self.signal_generator:
                    try:
                        regime_manager = self.signal_generator.regime_managers.get(symbol) or self.signal_generator.regime_manager
                        if regime_manager:
                            regime = regime_manager.get_current_regime()
                            if regime:
                                regime = str(regime).lower()
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить режим из signal_generator для {symbol}: {e}")
                
                # Альтернативный источник - DataRegistry
                if not regime and self.data_registry:
                    try:
                        regime_data = await self.data_registry.get_regime(symbol)
                        if regime_data and regime_data.get("regime"):
                            regime = str(regime_data.get("regime")).lower()
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить режим из DataRegistry для {symbol}: {e}")
                
                # Fallback только если все источники недоступны
                if not regime:
                    regime = "ranging"
                    logger.warning(
                        f"⚠️ Режим не определен для {symbol} (все источники недоступны), используется fallback 'ranging'"
                    )
            volatility = None

            # Получаем волатильность (ATR) из DataRegistry
            if self.data_registry:
                try:
                    atr = await self.data_registry.get_indicator(symbol, "atr")
                    if atr and price > 0:
                        volatility = atr / price  # ATR в процентах от цены
                except Exception as e:
                    logger.debug(
                        f"⚠️ Не удалось получить ATR для расчета волатильности: {e}"
                    )

            # ✅ КРИТИЧНОЕ ИСПРАВЛЕНИЕ (25.12.2025): Итеративный расчет leverage с учетом notional
            # Проблема: leverage зависит от размера позиции, а размер позиции зависит от leverage
            # Решение: итеративный расчет - сначала margin, потом leverage, потом пересчет notional
            leverage_config = 10  # Начальное значение для ranging (будет пересчитано)
            estimated_notional_usd = None
            
            try:
                # Получаем баланс для определения базового размера позиции
                balance = None
                if self.data_registry:
                    try:
                        balance_data = await self.data_registry.get_balance()
                        balance = balance_data.get("balance") if balance_data else None
                    except Exception:
                        pass
                
                if balance is None:
                    balance = await self.client.get_balance()
                
                if balance:
                    # Получаем профиль баланса для базового размера позиции (margin)
                    balance_profile = self.config_manager.get_balance_profile(balance)
                    base_margin_usd = balance_profile.get("base_position_usd") or balance_profile.get("min_position_usd", 50.0)
                    
                    # ✅ ИТЕРАЦИЯ 1: Рассчитываем leverage на основе базового margin
                    if self.adaptive_leverage:
                        leverage_config = await self.adaptive_leverage.calculate_leverage(
                            signal, regime, volatility, client=self.client, position_size_usd=base_margin_usd
                        )
                    else:
                        leverage_config = getattr(self.scalping_config, "leverage", 10)
                    
                    # ✅ ИТЕРАЦИЯ 2: Пересчитываем notional = margin * leverage
                    estimated_notional_usd = base_margin_usd * leverage_config
                    
                    # ✅ КРИТИЧНО: Снижаем плечо для ETH при большом notional (>$200) для защиты от ADL
                    if symbol == "ETH-USDT" and estimated_notional_usd > 200:
                        # Для ETH с notional > $200 снижаем плечо до 5-7x для защиты от ADL
                        max_leverage_for_eth = 7 if estimated_notional_usd > 300 else 5
                        if leverage_config > max_leverage_for_eth:
                            logger.warning(
                                f"🔒 [ADL_PROTECTION] {symbol}: Notional ${estimated_notional_usd:.2f} > $200, "
                                f"снижаем плечо с {leverage_config}x до {max_leverage_for_eth}x для защиты от ADL"
                            )
                            leverage_config = max_leverage_for_eth
                            # Пересчитываем notional с новым leverage
                            estimated_notional_usd = base_margin_usd * leverage_config
                    
                    logger.info(
                        f"📊 [LEVERAGE_ITERATIVE] {symbol}: Margin=${base_margin_usd:.2f}, "
                        f"Leverage={leverage_config}x, Notional=${estimated_notional_usd:.2f}"
                    )
            except Exception as e:
                logger.debug(f"⚠️ Не удалось рассчитать итеративный leverage: {e}, используем стандартный расчет")
                # Fallback: используем стандартный расчет leverage
                if self.adaptive_leverage:
                    leverage_config = await self.adaptive_leverage.calculate_leverage(
                        signal, regime, volatility, client=self.client, position_size_usd=None
                    )
                else:
                    leverage_config = getattr(self.scalping_config, "leverage", 10)

            # ✅ ИСПРАВЛЕНО (25.12.2025): Используем адаптивный леверидж если доступен, иначе fallback на фиксированный
            if not self.adaptive_leverage:
                # ✅ ИСПРАВЛЕНО: Проверяем инициализацию AdaptiveLeverage
                logger.warning(
                    f"⚠️ AdaptiveLeverage не инициализирован для {symbol}, проверяем конфиг..."
                )
                # Fallback на фиксированный leverage из конфига
                leverage_config = getattr(self.scalping_config, "leverage", None)
                if leverage_config is None or leverage_config <= 0:
                    logger.error(
                        f"❌ leverage не указан в конфиге для {symbol}, используем 3 (fallback). "
                        f"Добавьте leverage в config_futures.yaml!"
                    )
                    leverage_config = 3
                # ✅ УЛУЧШЕНИЕ: Детальное логирование левериджа
                volatility_str = f"{volatility*100:.2f}%" if volatility else "N/A"
                logger.info(
                    f"📊 [LEVERAGE_FINAL] {symbol}: Фиксированный леверидж={leverage_config}x (из конфига) | "
                    f"сила={signal.get('strength', 0.5):.2f}, режим={regime}, "
                    f"волатильность={volatility_str}"
                )
                # ✅ ИСПРАВЛЕНИЕ: Добавляем leverage в signal для использования в risk_manager
                signal["leverage"] = leverage_config
            else:
                # AdaptiveLeverage доступен - используем его
                logger.debug(
                    f"✅ AdaptiveLeverage доступен для {symbol}, используем адаптивный расчет"
                )
                # ✅ ИСПРАВЛЕНИЕ: Добавляем leverage в signal для использования в risk_manager
                signal["leverage"] = leverage_config

            # Определяем posSide на основе стороны сигнала
            signal_side = signal.get("side", "").lower()
            pos_side = "long" if signal_side == "buy" else "short"

            try:
                # ✅ Устанавливаем leverage с posSide (для hedge mode это обязательно)
                await self.client.set_leverage(
                    symbol, leverage_config, pos_side=pos_side
                )
                logger.debug(
                    f"✅ Плечо {leverage_config}x установлено для {symbol} с posSide='{pos_side}' перед открытием"
                )
            except Exception as e:
                # ✅ Если не получилось с posSide, пробуем без posSide (для net mode)
                try:
                    logger.debug(
                        f"⚠️ Попытка с posSide не удалась для {symbol}, пробуем без posSide: {e}"
                    )
                    await self.client.set_leverage(symbol, leverage_config)
                    logger.debug(
                        f"✅ Плечо {leverage_config}x установлено для {symbol} без posSide перед открытием"
                    )
                except Exception as e2:
                    # ✅ Если и без posSide не получилось, логируем предупреждение, но не блокируем открытие
                    logger.warning(
                        f"⚠️ Не удалось установить плечо {leverage_config}x для {symbol} перед открытием: {e2}"
                    )
                    if self.client.sandbox:
                        logger.info(
                            f"ℹ️ Sandbox mode: leverage не установлен на бирже через API для {symbol}, "
                            f"но расчеты используют leverage={leverage_config}x из signal. "
                            f"Позиция может открыться с другим leverage, установленным на бирже."
                        )

            # ✅ НОВОЕ: Рассчитываем размер позиции через RiskManager (используем DataRegistry)
            # Получаем баланс из DataRegistry
            balance = None
            if self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    balance = balance_data.get("balance") if balance_data else None
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка получения баланса из DataRegistry: {e}")

            # Fallback: если DataRegistry не доступен или нет данных
            if balance is None:
                balance = await self.client.get_balance()

            # ✅ НОВОЕ: Если это добавление к позиции, используем рассчитанный размер добавления
            if signal.get("is_addition") and signal.get("addition_size_usd"):
                addition_size_usd = signal.get("addition_size_usd")
                # Конвертируем размер добавления в монеты
                try:
                    details = await self.client.get_instrument_details(symbol)
                    ct_val = float(details.get("ctVal", 0.01))
                    # Размер в USD -> размер в монетах
                    addition_size_coins = addition_size_usd / price
                    # Размер в монетах -> размер в контрактах
                    position_size = addition_size_coins / ct_val
                    logger.info(
                        f"📊 [POSITION_SCALING] {symbol}: Используем размер добавления | "
                        f"addition_size_usd=${addition_size_usd:.2f}, "
                        f"position_size={position_size:.6f} контрактов"
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ [POSITION_SCALING] Ошибка конвертации addition_size_usd для {symbol}: {e}, "
                        f"используем стандартный расчет"
                    )
                    position_size = await self.risk_manager.calculate_position_size(
                        balance, price, signal, self.signal_generator
                    )
            else:
                position_size = await self.risk_manager.calculate_position_size(
                    balance, price, signal, self.signal_generator
                )

            if position_size <= 0:
                logger.warning(
                    f"⛔ {symbol}: Размер позиции слишком мал: {position_size}. "
                    f"Проверьте баланс, лимиты маржи или min_position_usd в конфиге."
                )
                return False
            
            # ✅ НОВОЕ (26.12.2025): Детальное логирование всех проверок перед открытием
            logger.info("=" * 80)
            logger.info(f"🔍 ПРОВЕРКИ ПЕРЕД ОТКРЫТИЕМ ПОЗИЦИИ для {symbol}:")
            logger.info(f"   Сигнал: {signal.get('side', 'N/A').upper()} @ ${price:.2f}, strength={signal.get('strength', 0):.2f}")
            logger.info(f"   Размер позиции: {position_size:.6f} контрактов")
            logger.info(f"   Леверидж: {leverage_config}x")
            
            # Проверка ADL rank
            # ✅ ИСПРАВЛЕНО (26.12.2025): Получаем ADL из позиций с биржи, так как DataRegistry не имеет метода get_adl_rank
            current_adl_rank = None
            try:
                if self.client:
                    all_positions = await self.client.get_positions()
                    if all_positions:
                        # Ищем позицию для нашего символа
                        inst_id = f"{symbol}-SWAP"
                        for pos in all_positions:
                            if pos.get("instId") == inst_id:
                                pos_size = float(pos.get("pos", "0") or 0)
                                if abs(pos_size) > 1e-8:  # Позиция существует
                                    adl_rank = pos.get("adlRank") or pos.get("adl")
                                    if adl_rank is not None:
                                        try:
                                            current_adl_rank = int(adl_rank)
                                            break
                                        except (ValueError, TypeError):
                                            pass
            except Exception as e:
                logger.debug(f"   ⚠️ Ошибка получения ADL rank для {symbol}: {e}")
            
            if current_adl_rank is not None:
                if current_adl_rank >= 4:
                    logger.warning(
                        f"   ⚠️ ADL rank: {current_adl_rank} (высокий риск авто-делевериджинга) - БЛОКИРУЕМ"
                    )
                    # Блокируем открытие позиции при высоком ADL
                    logger.warning(f"⛔ Открытие позиции {symbol} заблокировано: ADL rank {current_adl_rank} >= 4")
                    return
                else:
                    logger.info(f"   ✅ ADL rank: {current_adl_rank} (приемлемый)")
            else:
                logger.debug(f"   ⚠️ ADL rank: не доступен (позиция еще не открыта или данные не получены)")
            
            # Проверка маржи
            try:
                # ✅ ИСПРАВЛЕНО (26.12.2025): Детальное логирование проверки маржи
                margin_required = position_size * price / leverage_config  # margin в USD
                current_positions = await self.client.get_positions()
                
                # Получаем баланс для детального логирования
                balance = None
                margin_used = None
                margin_available = None
                try:
                    if self.data_registry:
                        balance_data = await self.data_registry.get_balance()
                        balance = balance_data.get("balance", 0) if balance_data else 0
                        margin_data = await self.data_registry.get_margin()
                        if margin_data:
                            margin_used = margin_data.get("used", 0)
                            margin_available = margin_data.get("available", 0)
                except Exception as e:
                    logger.debug(f"   ⚠️ Ошибка получения данных маржи для логирования: {e}")
                
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Исправлена ошибка форматирования строки
                balance_str = f"{balance:.2f}" if balance is not None else "N/A"
                margin_used_str = f"{margin_used:.2f}" if margin_used is not None else "N/A"
                margin_available_str = f"{margin_available:.2f}" if margin_available is not None else "N/A"
                logger.info(
                    f"   💰 Проверка маржи: требуется=${margin_required:.2f}, "
                    f"баланс=${balance_str}, "
                    f"использовано=${margin_used_str}, "
                    f"доступно=${margin_available_str}"
                )
                
                margin_check = await self.risk_manager.check_margin_safety(
                    margin_required,
                    current_positions
                )
                if margin_check:
                    logger.info(f"   ✅ Проверка маржи: пройдена")
                else:
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Исправлена ошибка форматирования строки
                    margin_available_str = f"{margin_available:.2f}" if margin_available is not None else "N/A"
                    margin_used_str = f"{margin_used:.2f}" if margin_used is not None else "N/A"
                    balance_str = f"{balance:.2f}" if balance is not None else "N/A"
                    logger.warning(
                        f"   ⚠️ Проверка маржи: НЕ пройдена - БЛОКИРУЕМ\n"
                        f"      Требуется маржи: ${margin_required:.2f}\n"
                        f"      Доступно маржи: ${margin_available_str}\n"
                        f"      Использовано маржи: ${margin_used_str}\n"
                        f"      Баланс: ${balance_str}"
                    )
            except Exception as e:
                logger.warning(f"   ⚠️ Проверка маржи: ошибка {e}")
            
            # Проверка риска ликвидации
            try:
                liquidation_check = await self.risk_manager.check_liquidation_risk(
                    symbol, pos_side, position_size * price / leverage_config, price
                )
                if liquidation_check:
                    logger.info(f"   ✅ Проверка риска ликвидации: пройдена")
                else:
                    logger.warning(f"   ⚠️ Проверка риска ликвидации: НЕ пройдена - БЛОКИРУЕМ")
            except Exception as e:
                logger.debug(f"   ⚠️ Проверка риска ликвидации: ошибка {e}")
            
            logger.info("=" * 80)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сначала проверяем реальные позиции на бирже перед проверкой MaxSizeLimiter
            # Это гарантирует, что мы не блокируем открытие позиции из-за устаревших данных в max_size_limiter
            try:
                all_positions = await self.client.get_positions()
                symbol_positions = [
                    p
                    for p in all_positions
                    if (
                        p.get("instId", "").replace("-SWAP", "") == symbol
                        or p.get("instId", "") == symbol
                    )
                    and abs(float(p.get("pos", "0"))) > 0.000001
                ]

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем все позиции на бирже (в том же и противоположном направлении)
                if len(symbol_positions) > 0:
                    signal_side = signal.get("side", "").lower() if signal else "buy"
                    signal_position_side = "long" if signal_side == "buy" else "short"

                    # Определяем все направления позиций на бирже
                    has_long = any(
                        float(p.get("pos", "0")) > 0
                        or p.get("posSide", "").lower() == "long"
                        for p in symbol_positions
                    )
                    has_short = any(
                        float(p.get("pos", "0")) < 0
                        or p.get("posSide", "").lower() == "short"
                        for p in symbol_positions
                    )

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Блокируем открытие противоположных позиций ДО открытия
                    allow_concurrent = getattr(
                        self.scalping_config, "allow_concurrent_positions", False
                    )

                    if (
                        signal_position_side == "long"
                        and has_short
                        and not allow_concurrent
                    ):
                        logger.warning(
                            f"⛔ БЛОКИРУЕМ LONG для {symbol}: уже есть SHORT позиция на бирже. "
                            f"Противоположные позиции не разрешены (allow_concurrent=false)"
                        )
                        return False
                    elif (
                        signal_position_side == "short"
                        and has_long
                        and not allow_concurrent
                    ):
                        logger.warning(
                            f"⛔ БЛОКИРУЕМ SHORT для {symbol}: уже есть LONG позиция на бирже. "
                            f"Противоположные позиции не разрешены (allow_concurrent=false)"
                        )
                        return False

                    # Проверяем, есть ли позиция в направлении сигнала (уже открыта - блокируем)
                    position_in_signal_direction = None
                    for pos in symbol_positions:
                        pos_size = float(pos.get("pos", "0"))
                        actual_side = "long" if pos_size > 0 else "short"

                        if actual_side == signal_position_side:
                            position_in_signal_direction = pos
                            break

                    if position_in_signal_direction:
                        # ✅ ИСПРАВЛЕНИЕ: Проверяем, является ли это добавлением к позиции
                        if signal.get("is_addition"):
                            # Это лестничное добавление - разрешаем продолжение
                            logger.info(
                                f"✅ [POSITION_SCALING] {symbol}: Позиция найдена, продолжаем добавление (is_addition=True)"
                            )
                        else:
                            # Позиция действительно есть на бирже в том же направлении - блокируем
                            pos_size = abs(
                                float(position_in_signal_direction.get("pos", "0"))
                            )
                            # ✅ ЛОГИРОВАНИЕ: Показываем, было ли переключение направления ADX
                            original_side = signal.get("original_side", "")
                            side_switched = signal.get("side_switched_by_adx", False)
                            if side_switched and original_side:
                                original_position_side = (
                                    "long"
                                    if original_side.lower() == "buy"
                                    else "short"
                                )
                                logger.warning(
                                    f"⚠️ Позиция {symbol} {signal_position_side.upper()} уже открыта на бирже (size={pos_size}), "
                                    f"БЛОКИРУЕМ новый {signal_side.upper()} ордер "
                                    f"(ADX переключил направление с {original_position_side.upper()} → {signal_position_side.upper()}, "
                                    f"но позиция уже открыта. На OKX Futures ордера объединяются, увеличивая комиссию)"
                                )
                            else:
                                logger.warning(
                                    f"⚠️ Позиция {symbol} {signal_position_side.upper()} уже открыта на бирже (size={pos_size}), "
                                    f"БЛОКИРУЕМ новый {signal_side.upper()} ордер "
                                    f"(на OKX Futures ордера в одном направлении объединяются, что увеличивает комиссию)"
                                )
                            return False
                    else:
                        # Позиция есть, но в другом направлении - очищаем max_size_limiter для корректной проверки
                        if symbol in self.max_size_limiter.position_sizes:
                            logger.debug(
                                f"🔄 Позиция {symbol} есть на бирже, но в другом направлении, "
                                f"очищаем max_size_limiter для корректной проверки"
                            )
                            self.max_size_limiter.remove_position(symbol)
                else:
                    # Позиции нет на бирже - очищаем max_size_limiter если там есть устаревшие данные
                    if symbol in self.max_size_limiter.position_sizes:
                        logger.debug(
                            f"🔄 Позиция {symbol} отсутствует на бирже, но есть в max_size_limiter, "
                            f"очищаем устаревшие данные"
                        )
                        self.max_size_limiter.remove_position(symbol)
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка проверки позиций на бирже для {symbol}: {e}, продолжаем проверку через MaxSizeLimiter"
                )

            # Проверка через MaxSizeLimiter
            # ⚠️ ИСПРАВЛЕНИЕ: size_usd = notional (номинальная стоимость), а не маржа!
            # ✅ ИСПРАВЛЕНИЕ: Используем рассчитанный leverage_config вместо дефолтного из конфига
            leverage = (
                leverage_config  # Используем адаптивный leverage, рассчитанный выше
            )
            logger.debug(
                f"📊 [LEVERAGE_USAGE] {symbol}: Используем leverage={leverage}x "
                f"для проверки MaxSizeLimiter и расчетов"
            )
            size_usd = position_size * price  # Это notional (номинальная стоимость)
            can_open, reason = self.max_size_limiter.can_open_position(symbol, size_usd)

            if not can_open:
                logger.warning(f"Нельзя открыть позицию: {reason}")
                return False

            # Проверка через FundingRateMonitor
            if not self.funding_monitor.is_funding_favorable(signal["side"]):
                logger.warning(f"Funding неблагоприятен для {signal['side']}")
                return False

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Последняя проверка перед размещением ордера (с нормализованным символом)
            # Проверяем, не был ли только что размещен ордер (даже если его еще нет в активных)
            current_time = time.time()
            normalized_symbol = (
                self.normalize_symbol_callback(symbol)
                if self.normalize_symbol_callback
                else symbol
            )
            if normalized_symbol in self.last_orders_cache_ref:
                last_order = self.last_orders_cache_ref[normalized_symbol]
                order_time = last_order.get("timestamp", 0)
                order_status = last_order.get("status", "unknown")
                time_since_order = current_time - order_time
                # ✅ УСИЛЕНО: Если ордер был размещен менее 15 секунд назад и pending - строго блокируем
                if time_since_order < 15 and order_status == "pending":
                    logger.warning(
                        f"⚠️ Ордер для {symbol} был размещен {time_since_order:.1f}s назад (status=pending), "
                        f"СТРОГО блокируем размещение дубликата (предотвращение двойных ордеров)"
                    )
                    return False
                # Если ордер был размещен менее 30 секунд назад и еще не исполнен/отменен - блокируем
                if time_since_order < 30 and order_status not in [
                    "filled",
                    "cancelled",
                    "rejected",
                ]:
                    logger.warning(
                        f"⚠️ Ордер для {symbol} был размещен {time_since_order:.1f}s назад, "
                        f"пропускаем размещение дубликата"
                    )
                    return False

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Финальная проверка активных ордеров ПЕРЕД размещением
            # Это предотвращает race condition, когда два сигнала проходят проверку одновременно
            try:
                active_orders = await self.client.get_active_orders(symbol)
                inst_id = f"{symbol}-SWAP"
                open_position_orders = [
                    o
                    for o in active_orders
                    if o.get("instId") == inst_id
                    and o.get("side", "").lower() in ["buy", "sell"]
                    and o.get("reduceOnly", "false").lower() != "true"
                ]

                if len(open_position_orders) > 0:
                    order_ids = [o.get("ordId") for o in open_position_orders]
                    logger.warning(
                        f"⚠️ Обнаружены {len(open_position_orders)} активных ордеров для {symbol} ПЕРЕД размещением: {order_ids}, "
                        f"БЛОКИРУЕМ размещение дубликата (race condition защита)"
                    )
                    return False
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка финальной проверки активных ордеров для {symbol}: {e}"
                )
                # При ошибке - лучше пропустить, чем создать дубликат
                return False

            # ✅ НОВОЕ: Получаем regime и balance_profile для EntryManager (используем DataRegistry)
            regime = signal.get("regime") if signal else None

            # Получаем режим из DataRegistry
            if not regime and symbol and self.data_registry:
                try:
                    regime_data = await self.data_registry.get_regime(symbol)
                    if regime_data:
                        regime = regime_data.get("regime")
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка получения режима из DataRegistry для {symbol}: {e}"
                    )

            # Fallback: если DataRegistry не доступен или нет данных
            if not regime and hasattr(self.signal_generator, "regime_managers"):
                manager = self.signal_generator.regime_managers.get(symbol)
                if manager:
                    regime = manager.get_current_regime()
            if not regime and hasattr(self.signal_generator, "regime_manager"):
                try:
                    regime = self.signal_generator.regime_manager.get_current_regime()
                except Exception:
                    regime = None

            # ✅ ПРОВЕРКА: Если regime не определен, это проблема адаптивной системы!
            if not regime:
                logger.warning(
                    f"⚠️ КРИТИЧНО: Режим не определен для {symbol} при открытии позиции! "
                    f"regime_managers={hasattr(self.signal_generator, 'regime_managers')}, "
                    f"regime_manager={hasattr(self.signal_generator, 'regime_manager')}, "
                    f"signal.regime={signal.get('regime')}. "
                    f"Используется fallback из signal или 'ranging'"
                )

            # ✅ НОВОЕ: Получаем balance_profile из DataRegistry
            balance_profile = None
            try:
                balance = None
                if self.data_registry:
                    try:
                        balance_data = await self.data_registry.get_balance()
                        if balance_data:
                            balance = balance_data.get("balance")
                            balance_profile = balance_data.get("profile")
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка получения баланса из DataRegistry: {e}"
                        )

                # Fallback: если DataRegistry не доступен или нет данных
                if balance is None:
                    balance = await self.client.get_balance()
                    balance_profile_data = self.config_manager.get_balance_profile(
                        balance
                    )
                    if balance_profile_data:
                        balance_profile = balance_profile_data.get("name")
            except Exception:
                pass

            # Получаем regime_params
            regime_params = None
            if regime:
                try:
                    regime_params = self.config_manager.get_regime_params(
                        regime, symbol
                    )
                except Exception:
                    pass

            # ✅ НОВОЕ: Используем EntryManager для централизованного открытия позиций
            # EntryManager откроет позицию через order_executor и зарегистрирует в PositionRegistry
            if self.entry_manager:
                result = await self.entry_manager.open_position_with_size(
                    signal=signal,
                    position_size=position_size,
                    regime=regime,
                    regime_params=regime_params,
                    balance_profile=balance_profile,
                )
            else:
                # Fallback: используем order_executor напрямую (для обратной совместимости)
                logger.warning(
                    f"⚠️ EntryManager не доступен, используем order_executor напрямую для {symbol}"
                )
                result = await self.order_executor.execute_signal(signal, position_size)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка на None перед использованием result
            if result is None:
                logger.error(
                    f"❌ execute_signal_from_price: result is None для {symbol}. "
                    f"entry_manager или order_executor вернул None вместо словаря результата."
                )
                return False

            if result.get("success"):
                order_id = result.get("order_id")
                order_type = result.get(
                    "order_type",
                    "limit",  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий
                )  # ✅ ЧАСТОТНЫЙ СКАЛЬПИНГ: "limit" для экономии комиссий

                # ✅ НОВОЕ: Для рыночных ордеров сразу записываем добавление (позиция открыта мгновенно)
                if (
                    signal.get("is_addition")
                    and self.position_scaling_manager
                    and order_type == "market"
                ):
                    try:
                        addition_size_usd = signal.get("addition_size_usd")
                        existing_leverage = await self.position_scaling_manager._get_existing_position_leverage(
                            symbol
                        )
                        if existing_leverage and addition_size_usd:
                            await self.position_scaling_manager.record_scaling_addition(
                                symbol=symbol,
                                addition_size_usd=addition_size_usd,
                                leverage=existing_leverage,
                            )
                            logger.info(
                                f"✅ [POSITION_SCALING] {symbol}: Записано добавление в историю (market) | "
                                f"size=${addition_size_usd:.2f}, leverage={existing_leverage}x"
                            )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ [POSITION_SCALING] Ошибка записи добавления в историю для {symbol}: {e}"
                        )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем кэш СРАЗУ после размещения ордера
                # Это предотвращает race condition, когда второй сигнал проходит проверку
                # до того, как первый ордер появится в API
                current_time = time.time()
                normalized_symbol = (
                    self.normalize_symbol_callback(symbol)
                    if self.normalize_symbol_callback
                    else symbol
                )
                self.last_orders_cache_ref[normalized_symbol] = {
                    "order_id": order_id,
                    "timestamp": current_time,
                    "status": "pending",  # Временно pending, будет обновлен после проверки
                    "order_type": order_type,
                    "side": signal.get("side", "unknown"),
                }
                logger.debug(
                    f"📦 Кэш обновлен СРАЗУ после размещения ордера {order_id} для {symbol} (race condition защита)"
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем, действительно ли позиция открылась
                # Для рыночных ордеров - сразу открыта (исполняются мгновенно)
                # Для лимитных ордеров - проверяем, что ордер исполнен
                position_opened = False
                if order_type == "market":
                    # Рыночный ордер - позиция открыта сразу
                    position_opened = True
                    logger.info(
                        f"✅ Рыночный ордер исполнен, позиция открыта: {symbol} {position_size:.6f}"
                    )
                else:
                    # Лимитный ордер - проверяем статус
                    try:
                        # ✅ ОПТИМИЗАЦИЯ: Уменьшено время ожидания с 2 сек до 0.5 сек для быстрого fallback
                        await asyncio.sleep(0.5)
                        # Проверяем статус ордера
                        active_orders = await self.client.get_active_orders(symbol)
                        inst_id = f"{symbol}-SWAP"
                        order_filled = True
                        for order in active_orders:
                            if (
                                str(order.get("ordId", "")) == str(order_id)
                                and order.get("instId") == inst_id
                            ):
                                # Ордер еще активен - не исполнен
                                order_filled = False
                                order_state = order.get("state", "").lower()
                                if order_state in ["filled", "partially_filled"]:
                                    order_filled = True
                                break

                        if order_filled:
                            # Проверяем, что позиция действительно открылась
                            positions = await self.client.get_positions()
                            for pos in positions:
                                pos_inst_id = pos.get("instId", "")
                                pos_size = abs(float(pos.get("pos", "0")))
                                if (
                                    pos_inst_id == inst_id or pos_inst_id == symbol
                                ) and pos_size > 0.000001:
                                    position_opened = True
                                    logger.info(
                                        f"✅ Лимитный ордер исполнен, позиция открыта: {symbol} {position_size:.6f}"
                                    )
                                    # ✅ НОВОЕ: Для лимитных ордеров записываем добавление после подтверждения открытия
                                    if (
                                        signal.get("is_addition")
                                        and self.position_scaling_manager
                                    ):
                                        try:
                                            addition_size_usd = signal.get(
                                                "addition_size_usd"
                                            )
                                            existing_leverage = await self.position_scaling_manager._get_existing_position_leverage(
                                                symbol
                                            )
                                            if existing_leverage and addition_size_usd:
                                                await self.position_scaling_manager.record_scaling_addition(
                                                    symbol=symbol,
                                                    addition_size_usd=addition_size_usd,
                                                    leverage=existing_leverage,
                                                )
                                                logger.info(
                                                    f"✅ [POSITION_SCALING] {symbol}: Записано добавление в историю (limit) | "
                                                    f"size=${addition_size_usd:.2f}, leverage={existing_leverage}x"
                                                )
                                        except Exception as e:
                                            logger.warning(
                                                f"⚠️ [POSITION_SCALING] Ошибка записи добавления в историю для {symbol}: {e}"
                                            )
                                    break

                        if not position_opened:
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем, не был ли ордер отменен
                            # ✅ ОПТИМИЗАЦИЯ: Уменьшено время ожидания с 1 сек до 0.3 сек
                            # ✅ НОВОЕ: Проверяем отклонение цены для немедленного fallback на market
                            try:
                                # ✅ ОПТИМИЗАЦИЯ: Проверяем отклонение цены от ордера для немедленного fallback на market
                                price_drift_pct = 0.0
                                should_fallback_market = False
                                try:
                                    # Получаем цену ордера из активных ордеров
                                    active_orders_check = (
                                        await self.client.get_active_orders(symbol)
                                    )
                                    order_price = 0.0
                                    for order in active_orders_check:
                                        if str(order.get("ordId", "")) == str(order_id):
                                            order_price = float(order.get("px", "0"))
                                            break

                                    # Если не нашли цену в активных, используем из order_result
                                    if order_price == 0:
                                        order_price = float(
                                            order_result.get("price", 0)
                                        )

                                    if order_price > 0:
                                        price_limits = (
                                            await self.client.get_price_limits(symbol)
                                        )
                                        if price_limits:
                                            current_price = price_limits.get(
                                                "current_price", 0
                                            )

                                            if current_price > 0:
                                                signal_side = (
                                                    signal.get("side", "").lower()
                                                    if signal
                                                    else "buy"
                                                )
                                                if signal_side == "buy":
                                                    # Для BUY: если цена ушла вниз > 0.05% от ордера
                                                    price_drift_pct = (
                                                        (order_price - current_price)
                                                        / order_price
                                                    ) * 100.0
                                                    if (
                                                        price_drift_pct > 0.05
                                                    ):  # Цена ушла вниз > 0.05%
                                                        should_fallback_market = True
                                                else:  # sell
                                                    # Для SELL: если цена ушла вверх > 0.05% от ордера
                                                    price_drift_pct = (
                                                        (current_price - order_price)
                                                        / order_price
                                                    ) * 100.0
                                                    if (
                                                        price_drift_pct > 0.05
                                                    ):  # Цена ушла вверх > 0.05%
                                                        should_fallback_market = True
                                except Exception as e:
                                    logger.debug(
                                        f"⚠️ Ошибка проверки отклонения цены для {symbol}: {e}"
                                    )

                                # Если цена ушла значительно - немедленный fallback на market
                                if should_fallback_market:
                                    logger.warning(
                                        f"💨 Цена ушла {price_drift_pct:.2f}% от лимитного ордера {order_id} для {symbol}, "
                                        f"отменяем и размещаем market ордер"
                                    )
                                    try:
                                        # Отменяем лимитный ордер
                                        await self.order_executor.cancel_order(
                                            order_id, symbol
                                        )
                                        # Размещаем market ордер
                                        market_result = await self.order_executor._place_market_order(
                                            symbol,
                                            signal.get("side", "buy"),
                                            position_size,
                                        )
                                        if market_result.get("success"):
                                            logger.info(
                                                f"✅ Market ордер размещен вместо лимитного для {symbol}: {market_result.get('order_id')}"
                                            )
                                            position_opened = True  # Market ордер исполняется мгновенно
                                            # ✅ НОВОЕ: Записываем добавление для fallback market ордера
                                            if (
                                                signal.get("is_addition")
                                                and self.position_scaling_manager
                                            ):
                                                try:
                                                    addition_size_usd = signal.get(
                                                        "addition_size_usd"
                                                    )
                                                    existing_leverage = await self.position_scaling_manager._get_existing_position_leverage(
                                                        symbol
                                                    )
                                                    if (
                                                        existing_leverage
                                                        and addition_size_usd
                                                    ):
                                                        await self.position_scaling_manager.record_scaling_addition(
                                                            symbol=symbol,
                                                            addition_size_usd=addition_size_usd,
                                                            leverage=existing_leverage,
                                                        )
                                                        logger.info(
                                                            f"✅ [POSITION_SCALING] {symbol}: Записано добавление в историю (fallback market) | "
                                                            f"size=${addition_size_usd:.2f}, leverage={existing_leverage}x"
                                                        )
                                                except Exception as e:
                                                    logger.warning(
                                                        f"⚠️ [POSITION_SCALING] Ошибка записи добавления в историю для {symbol}: {e}"
                                                    )
                                        else:
                                            logger.error(
                                                f"❌ Не удалось разместить market ордер для {symbol}: {market_result.get('error')}"
                                            )
                                    except Exception as e:
                                        logger.error(
                                            f"❌ Ошибка fallback на market для {symbol}: {e}"
                                        )

                                if not position_opened:
                                    await asyncio.sleep(0.3)
                                    # Проверяем статус ордера
                                    active_orders = await self.client.get_active_orders(
                                        symbol
                                    )
                                    order_cancelled = True
                                    for order in active_orders:
                                        if str(order.get("ordId", "")) == str(order_id):
                                            order_state = order.get("state", "").lower()
                                            if order_state in [
                                                "filled",
                                                "partially_filled",
                                            ]:
                                                # Ордер исполнен! Проверяем позицию еще раз
                                                positions = (
                                                    await self.client.get_positions()
                                                )
                                                for pos in positions:
                                                    pos_inst_id = pos.get("instId", "")
                                                    pos_size = abs(
                                                        float(pos.get("pos", "0"))
                                                    )
                                                    if (
                                                        pos_inst_id == inst_id
                                                        or pos_inst_id == symbol
                                                    ) and pos_size > 0.000001:
                                                        position_opened = True
                                                        logger.info(
                                                            f"✅ Лимитный ордер {order_id} исполнен после проверки, позиция открыта: {symbol}"
                                                        )
                                                        break
                                            order_cancelled = False
                                            break

                                    if order_cancelled:
                                        logger.warning(
                                            f"⚠️ Лимитный ордер {order_id} для {symbol} был отменен (возможно Slippage Guard), "
                                            f"позиция НЕ открылась"
                                        )
                                        # Обновляем кэш со статусом "cancelled"
                                        self.last_orders_cache_ref[
                                            normalized_symbol
                                        ] = {
                                            "order_id": order_id,
                                            "timestamp": current_time,
                                            "status": "cancelled",
                                            "order_type": order_type,
                                            "side": signal.get("side", "unknown"),
                                        }
                                        return False
                            except Exception as e:
                                logger.debug(
                                    f"Ошибка повторной проверки ордера {order_id}: {e}"
                                )

                            if not position_opened:
                                # ✅ ПРАВКА #3: Не считаем провалом если ордер в статусе pending
                                # Проверяем статус ордера
                                try:
                                    active_orders = await self.client.get_active_orders(
                                        symbol
                                    )
                                    order_found = False
                                    order_state = None

                                    for order in active_orders:
                                        if str(order.get("ordId", "")) == str(order_id):
                                            order_found = True
                                            order_state = order.get("state", "").lower()
                                            break

                                    if order_found and order_state in [
                                        "live",
                                        "pending",
                                        "partially_filled",
                                    ]:
                                        # ✅ Ордер еще активен - НЕ считаем провалом
                                        logger.info(
                                            f"⏳ Лимитный ордер {order_id} для {symbol} еще активен (state={order_state}), "
                                            f"ожидаем исполнения. Позиция будет инициализирована при исполнении через WebSocket."
                                        )
                                        # Обновляем кэш со статусом "pending"
                                        self.last_orders_cache_ref[
                                            normalized_symbol
                                        ] = {
                                            "order_id": order_id,
                                            "timestamp": current_time,
                                            "status": "pending",
                                            "order_type": order_type,
                                            "side": signal.get("side", "unknown"),
                                        }
                                        # ✅ НЕ возвращаем False - ордер может исполниться позже
                                        # Позиция будет инициализирована через WebSocket или при следующей проверке
                                        return True  # Считаем что процесс запущен, ждем исполнения
                                    else:
                                        # Ордер не найден или отменен - считаем провалом
                                        logger.warning(
                                            f"⚠️ Лимитный ордер {order_id} размещен для {symbol}, но позиция НЕ открылась "
                                            f"и ордер не найден в активных (state={order_state or 'unknown'}). "
                                            f"НЕ считаем позицию открытой!"
                                        )
                                        return False
                                except Exception as e:
                                    logger.error(
                                        f"Ошибка проверки статуса ордера {order_id}: {e}"
                                    )
                                    return False
                    except Exception as e:
                        logger.error(f"Ошибка проверки статуса ордера {order_id}: {e}")
                        # При ошибке - лучше не считать позицию открытой
                        return False

                # ✅ ТОЛЬКО если позиция действительно открылась - продолжаем
                if not position_opened:
                    logger.warning(
                        f"⚠️ Позиция {symbol} НЕ открылась после размещения ордера {order_id}"
                    )
                    return False

                # ✅ НОВОЕ: Логирование типа сигнала и примененных фильтров
                signal_type = (
                    signal.get("type") or signal.get("signal_type") or "unknown"
                )
                filters_passed = signal.get("filters_passed", [])
                regime = signal.get("regime") or "unknown"

                logger.info(
                    f"✅ Позиция открыта: {symbol} {position_size:.6f} | "
                    f"signal_type={signal_type} | regime={regime} | "
                    f"filters_passed={len(filters_passed)} ({', '.join(filters_passed[:3]) if filters_passed else 'none'})"
                )

                # ✅ НОВОЕ: Сохраняем в structured logs (если есть)
                if hasattr(self, "structured_logger") and self.structured_logger:
                    try:
                        self.structured_logger.log_signal(
                            symbol=symbol,
                            side=signal.get("side", "unknown"),
                            price=real_entry_price,
                            strength=signal.get("strength", 0.0),
                            regime=regime,
                            filters_passed=filters_passed,
                        )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка логирования сигнала в structured logs: {e}"
                        )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем кэш последних ордеров СРАЗУ после размещения (с нормализованным символом)
                if order_id:
                    self.last_orders_cache_ref[normalized_symbol] = {
                        "order_id": order_id,
                        "timestamp": current_time,
                        "status": "filled",  # ✅ Исправлено: статус filled, так как позиция открылась
                        "order_type": order_type,
                        "side": signal.get("side", "unknown"),
                    }
                    logger.debug(
                        f"📦 Обновлен кэш последнего ордера для {symbol}: {order_id} (status=filled)"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Синхронизация entry price с биржей после открытия позиции
                # Получаем реальную цену входа (avgPx) с биржи и обновляем trailing stop loss
                real_entry_price = price  # Fallback на цену сигнала
                try:
                    # ✅ ОПТИМИЗАЦИЯ: Уменьшено время ожидания с 2 сек до 0.5 сек для быстрой синхронизации
                    await asyncio.sleep(0.5)
                    # Получаем позицию с биржи
                    positions = await self.client.get_positions()
                    inst_id = f"{symbol}-SWAP"
                    for pos in positions:
                        pos_inst_id = pos.get("instId", "")
                        pos_size = abs(float(pos.get("pos", "0")))
                        if (
                            pos_inst_id == inst_id or pos_inst_id == symbol
                        ) and pos_size > 0.000001:
                            # Получаем реальную цену входа (avgPx) с биржи
                            avg_px = pos.get("avgPx")
                            if avg_px:
                                real_entry_price = float(avg_px)
                                logger.info(
                                    f"✅ Entry price синхронизирован для {symbol}: {price:.2f} → {real_entry_price:.2f} (avgPx с биржи)"
                                )
                            break
                except Exception as e:
                    logger.warning(
                        f"⚠️ Не удалось синхронизировать entry price для {symbol} с биржи: {e}, "
                        f"используем цену сигнала: {price:.2f}"
                    )

                # 🛡️ Обновляем total_margin_used
                # ⚠️ ИСПРАВЛЕНИЕ: Правильный расчет margin из position_size (монеты)
                # position_size в МОНЕТАХ, price в USD, leverage из конфига
                # margin = (size_in_coins × price) / leverage = notional / leverage
                # ✅ АДАПТИВНО: leverage из конфига
                leverage = getattr(self.scalping_config, "leverage", None)
                if leverage is None or leverage <= 0:
                    logger.error(
                        "❌ leverage не указан в конфиге! Проверьте config_futures.yaml"
                    )
                    leverage = 3  # Fallback только для расчета, но логируем ошибку
                    logger.warning(
                        f"⚠️ Используем fallback leverage={leverage}, но это не должно происходить!"
                    )
                notional = (
                    position_size * real_entry_price
                )  # Номинальная стоимость позиции (используем реальную цену входа)
                margin_used = notional / leverage  # Маржа = notional / leverage
                # ✅ МОДЕРНИЗАЦИЯ: Обновляем total_margin_used (будет пересчитано при следующей синхронизации)
                # Временно обновляем локально для быстрого доступа
                if self.total_margin_used_ref is not None:
                    self.total_margin_used_ref[0] += margin_used
                    logger.debug(
                        f"💼 Общая маржа: ${self.total_margin_used_ref[0]:.2f} "
                        f"(notional=${notional:.2f}, margin=${margin_used:.2f}, leverage={leverage}x)"
                    )
                # ✅ МОДЕРНИЗАЦИЯ: После открытия позиции синхронизируем маржу с биржей
                # Это гарантирует, что total_margin_used всегда актуален
                try:
                    # Быстрая синхронизация маржи (без полной синхронизации позиций)
                    if self.get_used_margin_callback:
                        updated_margin = await self.get_used_margin_callback()
                        if self.total_margin_used_ref is not None:
                            self.total_margin_used_ref[0] = updated_margin
                        logger.debug(
                            f"💼 Обновлена маржа с биржи: ${updated_margin:.2f} (после открытия позиции)"
                        )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Не удалось обновить маржу с биржи после открытия позиции: {e}"
                    )

                # 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Добавляем позицию в MaxSizeLimiter!
                # Без этого лимитер не отслеживает открытые позиции и разрешает открывать больше!
                size_usd_real = (
                    position_size * real_entry_price
                )  # Используем реальную цену входа
                self.max_size_limiter.add_position(symbol, size_usd_real)
                logger.debug(
                    f"✅ Позиция {symbol} добавлена в MaxSizeLimiter: ${size_usd_real:.2f} (всего: ${self.max_size_limiter.get_total_size():.2f})"
                )

                # Сохраняем в active_positions
                if symbol not in self.active_positions_ref:
                    self.active_positions_ref[symbol] = {}
                from datetime import timezone

                entry_time = datetime.now(timezone.utc)
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем режим из сигнала для сохранения в позиции
                # Режим должен быть в сигнале, так как он добавляется в signal_generator (строка 2330)
                regime = signal.get("regime") if signal else None

                # Логируем для отладки
                if signal:
                    logger.debug(
                        f"🔍 Режим в сигнале для {symbol}: {regime or 'НЕ НАЙДЕН'}"
                    )
                else:
                    logger.warning(
                        f"⚠️ Сигнал не передан в execute_signal_from_price для {symbol}!"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если режим не в сигнале, получаем из per-symbol ARM
                if not regime and hasattr(self.signal_generator, "regime_managers"):
                    manager = self.signal_generator.regime_managers.get(symbol)
                    if manager:
                        regime = manager.get_current_regime()
                        logger.debug(
                            f"📊 Режим для {symbol} получен из per-symbol ARM: {regime}"
                        )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Если режим все еще не найден, получаем из общего ARM
                if not regime and hasattr(self.signal_generator, "regime_manager"):
                    try:
                        regime = (
                            self.signal_generator.regime_manager.get_current_regime()
                        )
                        logger.debug(
                            f"📊 Режим для {symbol} получен из общего ARM: {regime}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Не удалось получить режим из общего ARM для {symbol}: {e}"
                        )

                # Логируем финальный режим для отладки
                if regime:
                    logger.debug(f"✅ Режим для {symbol} сохранен в позиции: {regime}")
                else:
                    logger.error(
                        f"❌ КРИТИЧЕСКАЯ ОШИБКА: Режим для {symbol} не найден при открытии позиции!"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Сохраняем position_side ("long"/"short") для правильного расчета PnL
                signal_side = signal.get("side", "").lower()
                position_side_for_storage = (
                    "long" if signal_side == "buy" else "short"
                )  # Конвертируем buy/sell в long/short

                # ✅ ЗАДАЧА #10: Получаем post_only из конфига для сохранения в позиции
                post_only = False
                try:
                    if regime:
                        regime_config = getattr(
                            self.scalping_config, f"{regime}_config", {}
                        )
                        limit_order_config = regime_config.get("limit_orders", {})
                        post_only = limit_order_config.get("post_only", False)
                    else:
                        limit_order_config = getattr(
                            self.scalping_config, "limit_orders", {}
                        )
                        if isinstance(limit_order_config, dict):
                            post_only = limit_order_config.get("post_only", False)
                except Exception:
                    post_only = False

                self.active_positions_ref[symbol].update(
                    {
                        "order_id": result.get("order_id"),
                        "side": signal[
                            "side"
                        ],  # "buy" или "sell" для внутреннего использования
                        "position_side": position_side_for_storage,  # "long" или "short" для правильного расчета PnL
                        "size": position_size,
                        "entry_price": real_entry_price,  # ✅ ИСПРАВЛЕНИЕ: Используем реальную цену входа с биржи
                        "margin": margin_used,  # margin для этой позиции
                        "entry_time": entry_time,  # ✅ НОВОЕ: Время открытия позиции
                        "timestamp": entry_time,  # Для совместимости
                        "time_extended": False,  # ✅ НОВОЕ: Флаг продления времени
                        "regime": regime,  # ✅ НОВОЕ: Сохраняем режим для per-regime TP
                        "order_type": order_type,  # ✅ ЗАДАЧА #10: Сохраняем тип ордера для расчета комиссии
                        "post_only": post_only,  # ✅ ЗАДАЧА #10: Сохраняем post_only для расчета комиссии
                        # ✅ БЕЗ tp_order_id и sl_order_id - используем TrailingSL!
                    }
                )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Переинициализируем trailing stop loss с правильной ценой входа
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем position_side_for_storage, который уже был рассчитан выше
                if self.initialize_trailing_stop_callback:
                    tsl = self.initialize_trailing_stop_callback(
                        symbol=symbol,
                        entry_price=real_entry_price,  # ✅ ИСПРАВЛЕНИЕ: Используем реальную цену входа с биржи
                        side=position_side_for_storage,  # "long" или "short", а не "buy"/"sell"
                        current_price=real_entry_price,  # ✅ ИСПРАВЛЕНИЕ: Используем реальную цену входа
                        signal=signal,
                    )
                    if tsl:
                        logger.info(
                            f"🎯 Позиция {symbol} открыта с TrailingSL (entry={real_entry_price:.2f})"
                        )
                    else:
                        logger.warning(
                            f"⚠️ TrailingStopLoss не был инициализирован для {symbol} (entry={real_entry_price:.2f})"
                        )
                else:
                    logger.warning(
                        f"⚠️ initialize_trailing_stop_callback не установлен для {symbol}"
                    )

                # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ ЛОГИРОВАНИЯ (26.12.2025): Добавляем детальную информацию
                # Получаем TP/SL параметры для логирования
                tp_percent = signal.get("tp_percent") if signal else None
                sl_percent = signal.get("sl_percent") if signal else None
                leverage_used = signal.get("leverage") if signal else None
                
                # Формируем детальное сообщение
                log_parts = [
                    f"✅ SignalCoordinator: Позиция {symbol} {position_side_for_storage.upper()} открыта",
                    f"entry_price={real_entry_price:.6f}",
                    f"size={position_size:.6f}",
                    f"regime={regime or 'unknown'}",
                ]
                
                if tp_percent:
                    log_parts.append(f"TP={tp_percent:.2f}%")
                else:
                    log_parts.append("TP=N/A")
                    
                if sl_percent:
                    log_parts.append(f"SL={sl_percent:.2f}%")
                else:
                    log_parts.append("SL=N/A")
                    
                if leverage_used:
                    log_parts.append(f"leverage={leverage_used}x")
                else:
                    log_parts.append("leverage=N/A")
                
                logger.info(" | ".join(log_parts))
                
                # Логируем открытие позиции в debug_logger
                if self.debug_logger:
                    self.debug_logger.log_position_open(
                        symbol=symbol,
                        side=position_side_for_storage,
                        entry_price=real_entry_price,
                        size=position_size,
                        regime=regime,
                    )

                return True
            else:
                error_msg = result.get("error", "Неизвестная ошибка")
                logger.error(f"❌ Не удалось разместить ордер для {symbol}: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"Ошибка выполнения сигнала: {e}", exc_info=True)
            return False

    async def _close_opposite_position(
        self, symbol: str, positions: List[Dict[str, Any]]
    ) -> None:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #1: Закрывает одну из противоположных позиций.

        Логика:
        - Находит LONG и SHORT позиции
        - Сравнивает их PnL
        - Закрывает убыточную (или меньшую прибыль)

        Args:
            symbol: Торговый символ
            positions: Список позиций с биржи
        """
        try:
            # Находим LONG и SHORT позиции
            long_pos = None
            short_pos = None

            for pos in positions:
                pos_side = pos.get("posSide", "").lower()
                pos_size = float(pos.get("pos", "0"))

                if pos_side == "long" or (
                    pos_size > 0 and pos_side not in ["long", "short"]
                ):
                    long_pos = pos
                elif pos_side == "short" or (
                    pos_size < 0 and pos_side not in ["long", "short"]
                ):
                    short_pos = pos

            if not long_pos or not short_pos:
                logger.warning(
                    f"⚠️ Не удалось найти обе противоположные позиции для {symbol}"
                )
                return

            # Получаем PnL для обеих позиций
            long_pnl = float(long_pos.get("upl", "0") or 0)
            short_pnl = float(short_pos.get("upl", "0") or 0)

            # Определяем, какую позицию закрывать
            # Закрываем убыточную (или меньшую прибыль)
            if long_pnl < short_pnl:
                pos_to_close = long_pos
                pos_side_to_close = "long"
                other_pnl = short_pnl
            else:
                pos_to_close = short_pos
                pos_side_to_close = "short"
                other_pnl = long_pnl

            pos_size = abs(float(pos_to_close.get("pos", "0")))
            pos_pnl = float(pos_to_close.get("upl", "0") or 0)

            logger.warning(
                f"🔄 Закрываем {symbol} {pos_side_to_close.upper()} позицию "
                f"(PnL={pos_pnl:.2f} USDT, другая позиция PnL={other_pnl:.2f} USDT, size={pos_size})"
            )

            # Закрываем позицию через client
            # Для закрытия используем reduce_only=True и указываем posSide
            close_side = "sell" if pos_side_to_close == "long" else "buy"

            result = await self.client.place_futures_order(
                symbol=symbol,
                side=close_side,
                size=pos_size,
                order_type="market",
                reduce_only=True,
                size_in_contracts=True,  # Размер уже в контрактах
            )

            if result.get("code") == "0":
                logger.info(
                    f"✅ Противоположная позиция {symbol} {pos_side_to_close.upper()} успешно закрыта "
                    f"(PnL={pos_pnl:.2f} USDT)"
                )
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(
                    f"❌ Не удалось закрыть противоположную позицию {symbol} {pos_side_to_close.upper()}: {error_msg}"
                )

        except Exception as e:
            logger.error(
                f"❌ Ошибка при закрытии противоположной позиции для {symbol}: {e}",
                exc_info=True,
            )
