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
from datetime import datetime
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
        self.config_manager = config_manager
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

                # Проверка минимальной силы сигнала
                if strength < self.scalping_config.min_signal_strength:
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
                        # ✅ КРИТИЧЕСКОЕ: Позиция уже есть в направлении сигнала
                        # На OKX Futures новый ордер в том же направлении просто увеличит размер позиции
                        # Это означает, что мы НЕ создаем новую позицию, а увеличиваем существующую
                        # Поэтому блокируем, чтобы не накапливать комиссию на одной позиции
                        pos_size = abs(
                            float(position_in_signal_direction.get("pos", "0"))
                        )
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
                                    if hasattr(self.client, "get_instrument_details"):
                                        try:
                                            details = await self.client.get_instrument_details(
                                                symbol
                                            )
                                            ct_val = float(details.get("ctVal", "1.0"))
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
                                "long" if original_side.lower() == "buy" else "short"
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

                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: НЕ закрываем противоположные позиции автоматически!
                        # Вместо этого БЛОКИРУЕМ новые сигналы до закрытия одной из позиций вручную или по TP/SL
                        if has_long and has_short and not allow_concurrent:
                            logger.warning(
                                f"🚨 Найдены противоположные позиции для {symbol} в process_signals: "
                                f"{len(symbol_positions)} позиций (LONG и SHORT). "
                                f"allow_concurrent=false, БЛОКИРУЕМ новые сигналы до закрытия одной из позиций. "
                                f"Позиции будут закрыты по TP/SL или вручную"
                            )
                            continue  # БЛОКИРУЕМ обработку сигнала, не закрываем автоматически
                        elif not allow_concurrent:
                            # РЕЖИМ 1: Не разрешаем несколько позиций (нет противоположных)
                            logger.debug(
                                f"⚠️ Позиция {symbol} в другом направлении уже открыта ({len(symbol_positions)} позиций), "
                                f"БЛОКИРУЕМ новые сигналы (allow_concurrent=false)"
                            )
                            continue
                        else:
                            # РЕЖИМ 2: Разрешаем позиции в разных направлениях, но проверяем лимит
                            if len(symbol_positions) >= max_positions_per_symbol:
                                logger.debug(
                                    f"⚠️ Достигнут лимит позиций по {symbol}: {len(symbol_positions)}/{max_positions_per_symbol}, "
                                    f"БЛОКИРУЕМ новые сигналы"
                                )
                                continue
                            else:
                                # Разрешаем - позиция в другом направлении (LONG + SHORT одновременно)
                                logger.debug(
                                    f"📊 Есть {len(symbol_positions)} позиция(й) по {symbol} в другом направлении, "
                                    f"разрешаем открытие {signal_position_side.upper()} позиции (allow_concurrent=true)"
                                )
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

            # ✅ ИСПРАВЛЕНО: Используем адаптивный risk_percentage из конфига по режиму
            # Если режим не определен, используем base_risk_percentage
            risk_percentage = None  # None - читает из конфига по режиму
            # Но если нужно использовать strength, умножаем base_risk_percentage
            base_risk = getattr(self.scalping_config, "base_risk_percentage", 0.03)
            if strength < 1.0:
                # Уменьшаем риск для слабых сигналов
                risk_percentage = base_risk * strength

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

                            if has_long and has_short:
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #1: Найдены противоположные позиции - АВТОМАТИЧЕСКИ ЗАКРЫВАЕМ одну из них
                                logger.warning(
                                    f"🚨 Найдены противоположные позиции для {symbol}: "
                                    f"{positions_info}. allow_concurrent=false, АВТОМАТИЧЕСКИ ЗАКРЫВАЕМ одну из позиций."
                                )
                                # Закрываем одну из противоположных позиций
                                await self._close_opposite_position(
                                    symbol, symbol_positions
                                )
                                return  # Блокируем генерацию сигналов после закрытия
                            else:
                                # Только одна позиция (нет противоположных) - блокируем новые сигналы
                                pos_raw = float(symbol_positions[0].get("pos", "0"))
                                pos_size = abs(pos_raw)
                                pos_side_raw = (
                                    symbol_positions[0].get("posSide", "").lower()
                                )
                                if pos_side_raw in ["long", "short"]:
                                    pos_side = pos_side_raw
                                else:
                                    pos_side = "long" if pos_raw > 0 else "short"
                                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Throttling для избыточных предупреждений
                                warning_key = f"{symbol}_{pos_side}_blocked"
                                current_time = time.time()
                                last_warning_time = self._last_warning_time.get(
                                    warning_key, 0
                                )

                                # Логируем только если прошло достаточно времени с последнего предупреждения
                                if (
                                    current_time - last_warning_time
                                    >= self._warning_throttle_seconds
                                ):
                                    logger.warning(
                                        f"⚠️ Позиция {symbol} {pos_side.upper()} УЖЕ ОТКРЫТА (size={pos_size}), "
                                        f"БЛОКИРУЕМ новые сигналы (allow_concurrent=false). "
                                        f"Позиции: {positions_info}"
                                    )
                                    self._last_warning_time[warning_key] = current_time
                                else:
                                    # Логируем только на DEBUG уровне если предупреждение недавно было
                                    logger.debug(
                                        f"⏭️ Позиция {symbol} {pos_side.upper()} заблокирована "
                                        f"(throttling: {int(self._warning_throttle_seconds - (current_time - last_warning_time))}s)"
                                    )
                                return
                        # Если allow_concurrent=true, проверка направления будет в process_signals

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

                    # ✅ ОПТИМИЗАЦИЯ: Убрано избыточное DEBUG логирование
                    # logger.debug(f"📊 Сгенерировано сигналов: {len(signals)}")

                    # Ищем сигнал для текущего символа
                    symbol_signal = None
                    for signal in signals:
                        if signal.get("symbol") == symbol:
                            symbol_signal = signal
                            break

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

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем и устанавливаем leverage перед открытием позиции
            # Учитываем режим позиций (hedge mode требует posSide)
            leverage_config = getattr(self.scalping_config, "leverage", None)
            if leverage_config is None or leverage_config <= 0:
                logger.warning(
                    f"⚠️ leverage не указан в конфиге для {symbol}, используем 3 (fallback)"
                )
                leverage_config = 3

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
                            f"⚠️ Sandbox mode: leverage не установлен на бирже через API для {symbol}, "
                            f"но расчеты используют leverage={leverage_config}x из конфига. "
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

            position_size = await self.risk_manager.calculate_position_size(
                balance, price, signal, self.signal_generator
            )

            if position_size <= 0:
                logger.warning(f"Размер позиции слишком мал: {position_size}")
                return False

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
                        # Позиция действительно есть на бирже в том же направлении - блокируем
                        pos_size = abs(
                            float(position_in_signal_direction.get("pos", "0"))
                        )
                        # ✅ ЛОГИРОВАНИЕ: Показываем, было ли переключение направления ADX
                        original_side = signal.get("original_side", "")
                        side_switched = signal.get("side_switched_by_adx", False)
                        if side_switched and original_side:
                            original_position_side = (
                                "long" if original_side.lower() == "buy" else "short"
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
            leverage = getattr(self.scalping_config, "leverage", 3)
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
                        # Ждем немного для исполнения лимитного ордера (1-2 секунды)
                        await asyncio.sleep(2)
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
                                    break

                        if not position_opened:
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем, не был ли ордер отменен
                            # Если ордер был отменен (например, Slippage Guard), но позиция не открылась,
                            # проверяем еще раз через 1 секунду на случай, если ордер был частично исполнен
                            try:
                                await asyncio.sleep(1)
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
                                    self.last_orders_cache_ref[normalized_symbol] = {
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

                logger.info(f"✅ Позиция открыта: {symbol} {position_size:.6f}")

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
                    # Ждем немного для синхронизации позиций на бирже (2-3 секунды)
                    await asyncio.sleep(2)
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
                entry_time = datetime.now()
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
