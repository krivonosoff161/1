"""
Trailing SL Coordinator для Futures торговли.

Координирует управление Trailing Stop Loss для всех позиций:
- Инициализация TSL для новых позиций
- Обновление TSL при изменении цены
- Периодическая проверка TSL
- Обработка закрытия позиций по TSL
- Интеграция с DebugLogger
"""

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from ..indicators.trailing_stop_loss import TrailingStopLoss


class TrailingSLCoordinator:
    """
    Координатор Trailing Stop Loss для Futures торговли.

    Управляет TSL для всех позиций, координируя взаимодействие между
    TSL индикатором, конфигурацией и логикой закрытия позиций.
    """

    def __init__(
        self,
        config_manager,
        debug_logger,
        signal_generator,
        client,
        scalping_config,
        get_position_callback: Callable[
            [str], Dict[str, Any]
        ],  # Синхронная функция для получения позиции
        close_position_callback: Callable[
            [str, str], Awaitable[None]
        ],  # Async функция для закрытия позиции
        get_current_price_callback: Callable[
            [str], Awaitable[Optional[float]]
        ],  # Async функция для получения цены
        active_positions_ref: Optional[
            Dict[str, Dict[str, Any]]
        ] = None,  # Ссылка на active_positions (опционально)
        fast_adx=None,
        position_manager=None,
        order_flow=None,  # ✅ ЭТАП 1.1: OrderFlowIndicator для анализа разворота
        exit_analyzer=None,  # ✅ НОВОЕ: ExitAnalyzer для анализа закрытия
    ):
        """
        Инициализация TrailingSLCoordinator.

        Args:
            config_manager: ConfigManager для получения параметров
            debug_logger: DebugLogger для логирования
            signal_generator: SignalGenerator для получения режима рынка
            client: Futures клиент для получения данных
            scalping_config: Конфигурация скальпинга
            get_position_callback: Функция для получения позиции по символу
            close_position_callback: Функция для закрытия позиции
            get_current_price_callback: Функция для получения текущей цены
            active_positions_ref: Ссылка на active_positions (опционально)
            fast_adx: FastADX индикатор (опционально)
            position_manager: PositionManager для profit harvesting (опционально)
            order_flow: OrderFlowIndicator для анализа разворота (опционально)
            exit_analyzer: ExitAnalyzer для анализа закрытия (опционально)
        """
        self.config_manager = config_manager  # Оставляем для обратной совместимости
        self.parameter_provider = None  # ✅ НОВОЕ (26.12.2025): ParameterProvider для единого доступа к параметрам
        self.debug_logger = debug_logger
        self.signal_generator = signal_generator
        self.client = client
        self.scalping_config = scalping_config
        self.get_position_callback = get_position_callback
        self.close_position_callback = close_position_callback
        self.get_current_price_callback = get_current_price_callback
        self.active_positions_ref = (
            active_positions_ref  # Для прямого доступа к active_positions
        )
        self.fast_adx = fast_adx
        self.position_manager = position_manager
        self.order_flow = (
            order_flow  # ✅ ЭТАП 1.1: OrderFlowIndicator для анализа разворота
        )
        self.exit_analyzer = (
            exit_analyzer  # ✅ НОВОЕ: ExitAnalyzer для анализа закрытия (fallback)
        )
        self.exit_decision_coordinator = None  # ✅ НОВОЕ (26.12.2025): ExitDecisionCoordinator для координации закрытия

        # ✅ ЭТАП 1.1: История delta для анализа разворота Order Flow
        self._order_flow_delta_history: Dict[
            str, list
        ] = {}  # symbol -> [(timestamp, delta), ...]

        # TSL для каждой позиции
        self.trailing_sl_by_symbol: Dict[str, TrailingStopLoss] = {}

        # Кэш для периодической проверки
        self._last_tsl_check_time: Dict[str, float] = {}

        # Интервалы проверки TSL
        tsl_config = getattr(self.scalping_config, "trailing_sl", {})
        self._tsl_check_interval: float = getattr(
            tsl_config, "check_interval_seconds", 1.5
        )
        self._tsl_check_intervals_by_regime: Dict[str, float] = {}

        # Счетчик логов
        self._tsl_log_count: Dict[str, int] = {}

        logger.info("✅ TrailingSLCoordinator initialized")

    def set_exit_decision_coordinator(self, exit_decision_coordinator):
        """
        ✅ НОВОЕ (26.12.2025): Установить ExitDecisionCoordinator для координации закрытия.

        Args:
            exit_decision_coordinator: Экземпляр ExitDecisionCoordinator
        """
        self.exit_decision_coordinator = exit_decision_coordinator
        logger.debug("✅ TrailingSLCoordinator: ExitDecisionCoordinator установлен")

    def set_parameter_provider(self, parameter_provider):
        """
        ✅ НОВОЕ (26.12.2025): Установить ParameterProvider для единого доступа к параметрам.

        Args:
            parameter_provider: Экземпляр ParameterProvider
        """
        self.parameter_provider = parameter_provider
        logger.debug("✅ TrailingSLCoordinator: ParameterProvider установлен")

    async def on_regime_change(self, new_regime: str, symbol: Optional[str] = None):
        """
        ✅ FIX: Перезагрузка параметров трейлинга при смене режима.

        Args:
            new_regime: Новый режим рынка (trending/ranging/choppy)
            symbol: Конкретный символ (если None — для всех)
        """
        try:
            # ✅ НОВОЕ (26.12.2025): Используем ParameterProvider вместо прямого обращения к config_manager
            if self.parameter_provider:
                # Для обновления режима используем config_manager напрямую (так как режим меняется для всех символов)
                params = self.config_manager.get_trailing_sl_params(new_regime)
            else:
                params = self.config_manager.get_trailing_sl_params(new_regime)
            if not params:
                logger.warning(f"⚠️ Не найдены TSL параметры для режима {new_regime}")
                return

            trail_distance_mult = params.get("trail_distance_multiplier", 1.0)
            trail_start_mult = params.get("trail_start_multiplier", 1.0)

            logger.info(
                f"TRAIL_RELOAD regime={new_regime} dist_mult={trail_distance_mult:.1f} start_mult={trail_start_mult:.1f}"
            )

            # Обновляем параметры для конкретного символа или всех
            symbols_to_update = (
                [symbol] if symbol else list(self.trailing_sl_by_symbol.keys())
            )

            for sym in symbols_to_update:
                tsl = self.trailing_sl_by_symbol.get(sym)
                if tsl:
                    # Обновляем multipliers в TSL объекте
                    if hasattr(tsl, "regime_multiplier"):
                        tsl.regime_multiplier = params.get("regime_multiplier", 1.0)
                    if hasattr(tsl, "high_profit_threshold"):
                        tsl.high_profit_threshold = params.get(
                            "high_profit_threshold", 0.01
                        )
                    if hasattr(tsl, "high_profit_max_factor"):
                        tsl.high_profit_max_factor = params.get(
                            "high_profit_max_factor", 2.0
                        )
                    logger.debug(f"✅ TSL для {sym} обновлён под режим {new_regime}")
        except Exception as e:
            logger.error(f"❌ Ошибка перезагрузки TSL параметров: {e}")

    def _get_position(self, symbol: str) -> Dict[str, Any]:
        """
        Вспомогательный метод для получения позиции.

        Использует active_positions_ref если доступно, иначе get_position_callback.

        Args:
            symbol: Торговый символ

        Returns:
            Словарь с данными позиции или пустой словарь
        """
        if self.active_positions_ref is not None:
            return self.active_positions_ref.get(symbol, {})
        return self.get_position_callback(symbol) or {}

    def _has_position(self, symbol: str) -> bool:
        """
        Вспомогательный метод для проверки наличия позиции.

        Args:
            symbol: Торговый символ

        Returns:
            True если позиция существует
        """
        if self.active_positions_ref is not None:
            return symbol in self.active_positions_ref
        position = self.get_position_callback(symbol)
        return position is not None and len(position) > 0

    def _get_trailing_sl_params(
        self, symbol: str, regime: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Получает параметры Trailing SL для символа и режима.

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending/ranging/choppy)

        Returns:
            Словарь с параметрами TSL или None
        """
        try:
            # Получаем режим если не указан
            if not regime:
                if hasattr(
                    self.signal_generator, "regime_managers"
                ) and symbol in getattr(self.signal_generator, "regime_managers", {}):
                    manager = self.signal_generator.regime_managers.get(symbol)
                    if manager:
                        regime = manager.get_current_regime()

            # ✅ НОВОЕ (26.12.2025): Используем ParameterProvider вместо прямого обращения к config_manager
            if self.parameter_provider:
                params = self.parameter_provider.get_trailing_sl_params(
                    symbol=symbol, regime=regime
                )
            else:
                # Fallback на config_manager
                params = self.config_manager.get_trailing_sl_params(regime=regime)
            return params
        except Exception as e:
            logger.debug(f"⚠️ Ошибка получения TSL параметров для {symbol}: {e}")
            return None

    def initialize_trailing_stop(
        self,
        symbol: str,
        entry_price: float,
        side: str,
        current_price: Optional[float] = None,
        signal: Optional[Dict[str, Any]] = None,
    ) -> Optional[TrailingStopLoss]:
        """
        Создает или переинициализирует TrailingStopLoss для указанного символа.

        Args:
            symbol: Торговый символ
            entry_price: Цена входа
            side: Сторона позиции ("buy"/"sell" или "long"/"short")
            current_price: Текущая цена (опционально)
            signal: Сигнал с режимом рынка (опционально)

        Returns:
            TrailingStopLoss или None если не удалось создать
        """
        if entry_price <= 0:
            return None

        # ✅ ЭТАП 4.5: Получаем режим рынка для адаптации параметров
        regime = signal.get("regime") if signal else None
        if (
            not regime
            and hasattr(self.signal_generator, "regime_managers")
            and symbol in getattr(self.signal_generator, "regime_managers", {})
        ):
            manager = self.signal_generator.regime_managers.get(symbol)
            if manager:
                regime = manager.get_current_regime()

        # ✅ ЭТАП 4: Получаем параметры с адаптацией под режим рынка
        # ✅ НОВОЕ (26.12.2025): Используем ParameterProvider вместо прямого обращения к config_manager
        if self.parameter_provider:
            params = self.parameter_provider.get_trailing_sl_params(
                symbol=symbol, regime=regime
            )
        else:
            # Fallback на config_manager
            params = self.config_manager.get_trailing_sl_params(regime=regime)

        # ✅ КРИТИЧЕСКОЕ ЛОГИРОВАНИЕ: Логируем режим и параметры для диагностики
        logger.info(
            f"🔍 TSL INIT для {symbol}: regime={regime}, "
            f"loss_cut={params.get('loss_cut_percent')}, "
            f"min_holding={params.get('min_holding_minutes')} мин, "
            f"timeout={params.get('timeout_minutes')} мин"
        )

        # Получаем дополнительные переопределения из профиля символа (если есть)
        regime_profile = self.config_manager.get_symbol_regime_profile(symbol, regime)
        trailing_overrides = (
            self.config_manager.to_dict(regime_profile.get("trailing_sl", {}))
            if regime_profile
            else {}
        )
        if trailing_overrides:
            for key, value in trailing_overrides.items():
                if key in params and value is not None:
                    # ✅ Безопасное преобразование типов
                    try:
                        if key == "extend_time_on_profit":
                            # Boolean значение
                            if isinstance(value, str):
                                params[key] = value.lower() in (
                                    "true",
                                    "1",
                                    "yes",
                                    "on",
                                )
                            else:
                                params[key] = bool(value)
                        elif key in (
                            "min_holding_minutes",
                            "extend_time_multiplier",
                            "timeout_minutes",
                        ):
                            # Float значения для времени
                            params[key] = float(value) if value is not None else None
                        else:
                            # Остальные числовые значения
                            params[key] = float(value)
                    except (TypeError, ValueError) as e:
                        logger.warning(
                            f"⚠️ Не удалось преобразовать {key}={value} в правильный тип: {e}"
                        )
                        # Оставляем значение по умолчанию
        # ✅ ГРОК ФИКС: TSL aggressive для strong signals (strength > 0.8)
        # Trail 0.4% после +0.6%, losscut 1.0% для быстрой фиксации профита
        signal_strength = signal.get("strength", 0.0) if signal else 0.0
        if signal_strength > 0.8:
            # Агрессивный TSL для сильных сигналов
            params["initial_trail"] = 0.004  # 0.4% trail
            params["loss_cut_percent"] = 0.01  # 1.0% losscut
            logger.info(
                f"🚀 TSL AGGRESSIVE для {symbol}: strength={signal_strength:.2f} > 0.8, "
                f"trail={params['initial_trail']:.2%}, losscut={params['loss_cut_percent']:.2%}"
            )

        impulse_trailing = None
        if signal and signal.get("is_impulse"):
            impulse_trailing = signal.get("impulse_trailing") or {}
            if impulse_trailing:
                params["initial_trail"] = impulse_trailing.get(
                    "initial_trail", params["initial_trail"]
                )

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (02.01.2026): Проверяем существование TSL перед инициализацией
        existing_tsl = self.trailing_sl_by_symbol.get(symbol)
        if existing_tsl:
            # ✅ ИСПРАВЛЕНИЕ: Если TSL уже существует и параметры не изменились, не переинициализируем
            # Проверяем, изменились ли критичные параметры (trail, loss_cut)
            existing_trail = getattr(existing_tsl, "initial_trail", None)
            existing_loss_cut = getattr(existing_tsl, "loss_cut_percent", None)
            new_trail = params.get("initial_trail", 0.0)
            new_loss_cut = params.get("loss_cut_percent", 0.0)

            # Если параметры не изменились и entry_price совпадает, не переинициализируем
            if (
                existing_trail == new_trail
                and existing_loss_cut == new_loss_cut
                and abs(getattr(existing_tsl, "entry_price", 0) - entry_price) < 0.01
            ):
                logger.debug(
                    f"ℹ️ TSL для {symbol} уже существует с теми же параметрами "
                    f"(trail={new_trail:.2%}, loss_cut={new_loss_cut:.2%}, entry={entry_price:.2f}), "
                    f"пропускаем повторную инициализацию"
                )
                return existing_tsl

            # Параметры изменились или entry_price отличается - переинициализируем
            logger.info(
                f"🔄 TSL для {symbol} переинициализируется: "
                f"trail={existing_trail:.2%}→{new_trail:.2%}, "
                f"loss_cut={existing_loss_cut:.2%}→{new_loss_cut:.2%}, "
                f"entry={getattr(existing_tsl, 'entry_price', 0):.2f}→{entry_price:.2f}"
            )
            existing_tsl.reset()

        initial_trail = params["initial_trail"] or 0.0
        max_trail = params["max_trail"] or initial_trail
        min_trail = params["min_trail"] or 0.0
        trading_fee_rate = params["trading_fee_rate"] or 0.0

        # ✅ ЭТАП 4: Создаем TrailingStopLoss с новыми параметрами
        # ✅ КРИТИЧЕСКОЕ: Получаем leverage из конфига для правильного расчета loss_cut от маржи
        leverage = getattr(self.scalping_config, "leverage", 3)
        if leverage is None or leverage <= 0:
            leverage = 3
            logger.warning(
                f"⚠️ leverage не указан в конфиге для {symbol}, используем 3 (fallback)"
            )

        tsl = TrailingStopLoss(
            initial_trail=initial_trail,
            max_trail=max_trail,
            min_trail=min_trail,
            trading_fee_rate=trading_fee_rate,
            loss_cut_percent=params["loss_cut_percent"],
            timeout_loss_percent=params["timeout_loss_percent"],
            timeout_minutes=params["timeout_minutes"],
            min_holding_minutes=params["min_holding_minutes"],  # ✅ ЭТАП 4.4
            min_profit_to_close=params["min_profit_to_close"],  # ✅ ЭТАП 4.1
            extend_time_on_profit=params["extend_time_on_profit"],  # ✅ ЭТАП 4.3
            extend_time_multiplier=params["extend_time_multiplier"],  # ✅ ЭТАП 4.3
            leverage=leverage,  # ✅ КРИТИЧЕСКОЕ: Передаем leverage для правильного расчета loss_cut от маржи
            min_critical_hold_seconds=params.get(
                "min_critical_hold_seconds"
            ),  # ✅ КРИТИЧЕСКОЕ: Минимальное время для критических убытков (из конфига)
            # ✅ НОВОЕ: Передаем trail_growth multipliers для адаптивного трейлинга
            trail_growth_low_multiplier=params.get("trail_growth_low_multiplier", 1.5),
            trail_growth_medium_multiplier=params.get(
                "trail_growth_medium_multiplier", 2.0
            ),
            trail_growth_high_multiplier=params.get(
                "trail_growth_high_multiplier", 3.0
            ),
            debug_logger=self.debug_logger,  # ✅ DEBUG LOGGER для логирования
        )

        # ✅ АДАПТИВНО: Устанавливаем параметры из конфига для TSL
        tsl.regime_multiplier = params.get("regime_multiplier", 1.0)
        tsl.trend_strength_boost = params.get("trend_strength_boost", 1.0)
        tsl.high_profit_threshold = params.get("high_profit_threshold", 0.01)
        tsl.high_profit_max_factor = params.get("high_profit_max_factor", 2.0)
        tsl.high_profit_reduction_percent = params.get(
            "high_profit_reduction_percent", 30
        )
        tsl.high_profit_min_reduction = params.get("high_profit_min_reduction", 0.5)

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Конвертируем side в position_side ("long"/"short")
        # side может быть "buy"/"sell" или "long"/"short", нормализуем до "long"/"short"
        side_lower = side.lower()
        if side_lower in ["buy", "long"]:
            position_side = "long"
        elif side_lower in ["sell", "short"]:
            position_side = "short"
        else:
            logger.error(
                f"❌ Неизвестная сторона позиции: {side} для {symbol}. Используем 'long' по умолчанию."
            )
            position_side = "long"

        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем entry_timestamp из entry_time позиции для правильной инициализации TSL
        entry_timestamp_for_tsl = None
        if signal and signal.get("entry_time"):
            entry_time_obj = signal.get("entry_time")
            if isinstance(entry_time_obj, datetime):
                entry_timestamp_for_tsl = entry_time_obj.timestamp()
            elif isinstance(entry_time_obj, (int, float)):
                # Если уже timestamp (в секундах или миллисекундах)
                if entry_time_obj > 1e10:  # Это миллисекунды
                    entry_timestamp_for_tsl = entry_time_obj / 1000.0
                else:  # Это секунды
                    entry_timestamp_for_tsl = float(entry_time_obj)

        # ✅ НОВОЕ (03.01.2026): Логирование TP/SL параметров при открытии позиции
        try:
            if self.parameter_provider:
                exit_params = self.parameter_provider.get_exit_params(
                    symbol=symbol, regime=regime
                )
                if exit_params:
                    tp_atr_mult = exit_params.get("tp_atr_multiplier")
                    sl_atr_mult = exit_params.get("sl_atr_multiplier")
                    max_holding = exit_params.get("max_holding_minutes")
                    min_holding = exit_params.get("min_holding_minutes")

                    # Форматируем значения для логирования
                    tp_atr_str = (
                        f"{tp_atr_mult:.2f}" if tp_atr_mult is not None else "N/A"
                    )
                    sl_atr_str = (
                        f"{sl_atr_mult:.2f}" if sl_atr_mult is not None else "N/A"
                    )
                    max_holding_str = (
                        f"{max_holding:.1f}" if max_holding is not None else "N/A"
                    )
                    min_holding_str = (
                        f"{min_holding:.1f}" if min_holding is not None else "N/A"
                    )

                    logger.info(
                        f"📊 [PARAMS] {symbol} ({regime or 'unknown'}): TP/SL ПАРАМЕТРЫ ПРИ ОТКРЫТИИ | "
                        f"tp_atr_multiplier={tp_atr_str}, sl_atr_multiplier={sl_atr_str}, "
                        f"max_holding={max_holding_str}мин, min_holding={min_holding_str}мин | "
                        f"Источник: ParameterProvider.get_exit_params()"
                    )
        except Exception as e:
            logger.debug(
                f"⚠️ Ошибка логирования TP/SL параметров при открытии для {symbol}: {e}"
            )

        # ✅ ЭТАП 4.4: Инициализируем с правильной стороной (long/short) и entry_timestamp
        tsl.initialize(
            entry_price=entry_price,
            side=position_side,
            symbol=symbol,
            entry_timestamp=entry_timestamp_for_tsl,  # ✅ КРИТИЧЕСКОЕ: Передаем реальное время открытия
        )
        if impulse_trailing:
            step_profit = float(impulse_trailing.get("step_profit", 0) or 0)
            step_trail = float(impulse_trailing.get("step_trail", 0) or 0)
            aggressive_cap = impulse_trailing.get("aggressive_max_trail")
            if step_profit > 0 and step_trail > 0:
                tsl.enable_aggressive_mode(
                    step_profit=step_profit,
                    step_trail=step_trail,
                    aggressive_max_trail=aggressive_cap,
                )
                logger.info(
                    f"🚀 TrailingSL импульсный режим для {symbol}: step_profit={step_profit:.3%}, "
                    f"step_trail={step_trail:.3%}, cap={aggressive_cap if aggressive_cap else 'auto'}"
                )
        if current_price and current_price > 0:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: При инициализации margin/unrealized_pnl еще нет, передаем None
            tsl.update(current_price, margin_used=None, unrealized_pnl=None)
        self.trailing_sl_by_symbol[symbol] = tsl
        fee_display = trading_fee_rate if trading_fee_rate else 0.0
        # ✅ ИСПРАВЛЕНИЕ: loss_cut_percent уже в процентах (1.8 = 1.8%), не нужно умножать на 100
        loss_cut_display = (
            params["loss_cut_percent"] if params["loss_cut_percent"] else 0.0
        )
        logger.info(
            f"✅ TrailingStopLoss для {symbol} инициализирован: "
            f"trail={tsl.current_trail:.3%}, fee={fee_display:.3%}, "
            f"loss_cut={loss_cut_display:.2f}% от маржи, "
            f"min_holding={params['min_holding_minutes']:.1f} мин, "
            f"regime={regime or 'N/A'}"
        )

        # ✅ DEBUG LOGGER: Логируем создание TSL
        if self.debug_logger:
            self.debug_logger.log_tsl_created(
                symbol=symbol,
                regime=regime or "unknown",
                entry_price=entry_price,
                side=position_side,
                min_holding=params.get("min_holding_minutes"),
                timeout=params.get("timeout_minutes"),
            )

        # ✅ DEBUG LOGGER: Логируем загруженные параметры конфига
        if self.debug_logger:
            self.debug_logger.log_config_loaded(
                symbol=symbol, regime=regime or "unknown", params=params
            )

        return tsl

    async def update_trailing_stop_loss(self, symbol: str, current_price: float):
        """Обновление TrailingStopLoss для открытой позиции"""
        try:
            position = self._get_position(symbol)
            if not position:
                return

            entry_price = position.get("entry_price", 0)
            if isinstance(entry_price, str):
                try:
                    entry_price = float(entry_price)
                except (ValueError, TypeError):
                    entry_price = 0

            if entry_price == 0:
                avg_px = position.get("avgPx", 0)
                if isinstance(avg_px, str):
                    try:
                        avg_px = float(avg_px)
                    except (ValueError, TypeError):
                        avg_px = 0
                if avg_px and avg_px > 0:
                    entry_price = float(avg_px)
                    position["entry_price"] = entry_price
                    logger.info(
                        f"✅ Восстановлен entry_price={entry_price:.2f} для {symbol} из avgPx"
                    )
                else:
                    try:
                        positions = await self.client.get_positions(symbol)
                        if positions:
                            for pos in positions:
                                pos_size = float(pos.get("pos", "0"))
                                if abs(pos_size) > 1e-8:
                                    api_avg_px_raw = pos.get("avgPx", "0")
                                    try:
                                        api_avg_px = float(api_avg_px_raw)
                                    except (ValueError, TypeError):
                                        api_avg_px = 0
                                    if api_avg_px and api_avg_px > 0:
                                        entry_price = api_avg_px
                                        position["entry_price"] = entry_price
                                        position["avgPx"] = entry_price
                                        logger.info(
                                            f"✅ Восстановлен entry_price={entry_price:.2f} для {symbol} через API (после Partial TP)"
                                        )
                                        break
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить entry_price для {symbol} через API: {e}"
                        )

                    if entry_price == 0:
                        # ✅ TODO #5: Не блокируем другие проверки, если entry_price == 0
                        logger.warning(
                            f"⚠️ Entry price = 0 для {symbol}, avgPx={avg_px}, не можем обновить TSL"
                        )
                        # ✅ Проверяем, есть ли позиция вообще
                        if not self._has_position(symbol):
                            return
                        # ✅ Позиция существует, но entry_price=0 - это проблема, но не критично для других проверок
                        logger.debug(
                            f"⚠️ Позиция {symbol} существует, но entry_price=0, пропускаем обновление TSL "
                            f"(loss_cut может быть проверен в position_manager)"
                        )
                        return

            if symbol not in self.trailing_sl_by_symbol:
                logger.warning(
                    f"⚠️ TrailingStopLoss не инициализирован для {symbol} "
                    f"(позиция найдена в active_positions, но нет в trailing_sl_by_symbol). "
                    f"Инициализируем TSL автоматически..."
                )

                try:
                    pos_size = float(position.get("pos", position.get("size", "0")))
                    pos_side = position.get("posSide") or position.get(
                        "position_side", "long"
                    )

                    if entry_price <= 0:
                        avg_px = float(position.get("avgPx", "0") or 0)
                        if avg_px > 0:
                            entry_price = avg_px

                    if entry_price > 0 and abs(pos_size) > 0:
                        if "entry_time" not in position:
                            c_time = position.get("cTime")
                            u_time = position.get("uTime")
                            entry_time_str = c_time or u_time
                            if entry_time_str:
                                try:
                                    entry_timestamp = int(entry_time_str) / 1000
                                    # ✅ ИСПРАВЛЕНО: Добавляем timezone.utc
                                    from datetime import timezone

                                    position["entry_time"] = datetime.fromtimestamp(
                                        entry_timestamp, tz=timezone.utc
                                    )
                                    position["timestamp"] = position["entry_time"]
                                    logger.debug(
                                        f"✅ Установлен entry_time для {symbol} из cTime/uTime: {position['entry_time']}"
                                    )
                                except (ValueError, TypeError) as e:
                                    logger.warning(
                                        f"⚠️ Не удалось распарсить cTime/uTime для {symbol}: {e}, используем текущее время"
                                    )
                                    from datetime import timezone

                                    position["entry_time"] = datetime.now(timezone.utc)
                                    position["timestamp"] = position["entry_time"]
                            else:
                                from datetime import timezone

                                position["entry_time"] = datetime.now(timezone.utc)
                                position["timestamp"] = position["entry_time"]
                                logger.debug(
                                    f"⚠️ entry_time не найден для {symbol}, используем текущее время"
                                )

                        # ✅ КРИТИЧЕСКОЕ: Получаем entry_time из позиции для передачи в TSL
                        entry_time_from_pos = position.get("entry_time")
                        signal_with_entry_time = None
                        if entry_time_from_pos:
                            signal_with_entry_time = {"entry_time": entry_time_from_pos}

                        tsl = self.initialize_trailing_stop(
                            symbol=symbol,
                            entry_price=entry_price,
                            side=pos_side,
                            current_price=current_price,
                            signal=signal_with_entry_time,  # ✅ КРИТИЧЕСКОЕ: Передаем entry_time
                        )

                        if tsl:
                            logger.info(
                                f"✅ TrailingStopLoss автоматически инициализирован для {symbol} "
                                f"(entry={entry_price:.5f}, side={pos_side}, size={pos_size}, "
                                f"entry_time={position.get('entry_time', 'N/A')})"
                            )
                        else:
                            logger.error(
                                f"❌ Не удалось инициализировать TSL для {symbol}"
                            )
                            return
                    else:
                        logger.warning(
                            f"⚠️ Недостаточно данных для инициализации TSL для {symbol}: "
                            f"entry_price={entry_price}, size={pos_size}"
                        )
                        return
                except Exception as e:
                    logger.error(
                        f"❌ Ошибка автоматической инициализации TSL для {symbol}: {e}"
                    )
                    return

                if symbol not in self.trailing_sl_by_symbol:
                    logger.error(
                        f"❌ TSL для {symbol} не инициализирован после попытки автоматической инициализации"
                    )
                    return

            tsl = self.trailing_sl_by_symbol[symbol]

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем margin и unrealizedPnl ДО вызова update()
            margin_used = None
            unrealized_pnl = None
            try:
                margin_str = position.get("margin") or position.get("imr") or "0"
                if margin_str and str(margin_str).strip() and str(margin_str) != "0":
                    margin_used = float(margin_str)
                upl_str = position.get("upl") or position.get("unrealizedPnl") or "0"
                if upl_str and str(upl_str).strip() and str(upl_str) != "0":
                    unrealized_pnl = float(upl_str)
            except (ValueError, TypeError) as e:
                logger.debug(
                    f"⚠️ TrailingSLCoordinator: Ошибка получения margin/upl для {symbol}: {e}"
                )

            # ✅ ГРОК РЕКОМЕНДАЦИЯ: Проверка min_profit_to_activate перед обновлением trailing stop
            try:
                # Получаем параметры trailing_sl из конфига
                trailing_sl_config = getattr(self.scalping_config, "trailing_sl", {})
                if isinstance(trailing_sl_config, dict):
                    min_profit_to_activate = trailing_sl_config.get(
                        "min_profit_to_activate", 0.008
                    )
                else:
                    min_profit_to_activate = getattr(
                        trailing_sl_config, "min_profit_to_activate", 0.008
                    )

                # Рассчитываем текущий PnL%
                if entry_price > 0:
                    pos_side = position.get("posSide") or position.get(
                        "position_side", "long"
                    )
                    if pos_side.lower() == "long":
                        pnl_percent = (current_price - entry_price) / entry_price
                    else:  # short
                        pnl_percent = (entry_price - current_price) / entry_price

                    # Если прибыль меньше минимума - не обновляем trailing stop
                    if pnl_percent < min_profit_to_activate:
                        logger.debug(
                            f"⏸️ Trailing SL не активирован для {symbol}: "
                            f"PnL {pnl_percent:.2%} < минимум {min_profit_to_activate:.2%}"
                        )
                        return  # Не обновляем trailing до достижения минимума
            except Exception as e:
                logger.debug(
                    f"⚠️ Ошибка проверки min_profit_to_activate для {symbol}: {e}, продолжаем обновление"
                )
                # Продолжаем обновление при ошибке

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Передаем margin и unrealizedPnl в update() для правильного расчета от маржи
            tsl.update(
                current_price,
                margin_used=margin_used if margin_used and margin_used > 0 else None,
                unrealized_pnl=unrealized_pnl if unrealized_pnl is not None else None,
            )

            stop_loss = tsl.get_stop_loss()

            profit_pct = tsl.get_profit_pct(
                current_price,
                include_fees=True,
                margin_used=margin_used if margin_used and margin_used > 0 else None,
                unrealized_pnl=unrealized_pnl if unrealized_pnl is not None else None,
            )
            profit_pct_gross = tsl.get_profit_pct(
                current_price,
                include_fees=False,
                margin_used=margin_used if margin_used and margin_used > 0 else None,
                unrealized_pnl=unrealized_pnl if unrealized_pnl is not None else None,
            )

            # ✅ FIX: TRAIL_DISTANCE_NARROW warning — слишком узкая дистанция
            if stop_loss and current_price > 0:
                distance_pct = abs(current_price - stop_loss) / current_price * 100
                if distance_pct < 0.05:
                    logger.warning(
                        f"TRAIL_DISTANCE_NARROW {symbol} {distance_pct:.2f}%"
                    )

            position_side = position.get(
                "position_side", position.get("posSide", "long")
            )
            if position_side.lower() == "short":
                extremum = tsl.lowest_price
                extremum_label = "lowest"
            else:
                extremum = tsl.highest_price
                extremum_label = "highest"

            # ✅ ЭТАП 2.2: Улучшенный анализ силы тренда (ADX + Order Flow + Multi-Timeframe)
            trend_strength = None
            market_regime = None
            trend_analysis = {
                "adx": None,
                "order_flow": None,
                "multi_timeframe": None,
                "combined": None,
            }

            try:
                # 1. ADX анализ
                if self.fast_adx:
                    adx_value = self.fast_adx.get_current_adx()
                    if adx_value and adx_value > 0:
                        trend_analysis["adx"] = min(adx_value / 100.0, 1.0)
                        trend_strength = trend_analysis["adx"]

                # 2. Order Flow анализ
                if self.order_flow:
                    try:
                        current_delta = self.order_flow.get_delta()
                        avg_delta = self.order_flow.get_avg_delta(periods=10)
                        delta_trend = self.order_flow.get_delta_trend()

                        # Определяем силу тренда по Order Flow
                        if position_side.lower() == "long":
                            # Для LONG: положительный delta = сильный тренд
                            if current_delta > 0.1 and delta_trend == "long":
                                trend_analysis["order_flow"] = min(
                                    abs(current_delta) * 2, 1.0
                                )
                            elif current_delta > 0.05:
                                trend_analysis["order_flow"] = min(
                                    abs(current_delta) * 1.5, 0.7
                                )
                        elif position_side.lower() == "short":
                            # Для SHORT: отрицательный delta = сильный тренд
                            if current_delta < -0.1 and delta_trend == "short":
                                trend_analysis["order_flow"] = min(
                                    abs(current_delta) * 2, 1.0
                                )
                            elif current_delta < -0.05:
                                trend_analysis["order_flow"] = min(
                                    abs(current_delta) * 1.5, 0.7
                                )
                    except Exception as e:
                        logger.debug(f"⚠️ Ошибка анализа Order Flow для {symbol}: {e}")

                # 3. Комбинированный анализ силы тренда
                if (
                    trend_analysis["adx"] is not None
                    or trend_analysis["order_flow"] is not None
                ):
                    # Взвешенная комбинация: ADX 60%, Order Flow 40%
                    adx_weight = 0.6
                    of_weight = 0.4

                    adx_val = (
                        trend_analysis["adx"]
                        if trend_analysis["adx"] is not None
                        else 0.5
                    )
                    of_val = (
                        trend_analysis["order_flow"]
                        if trend_analysis["order_flow"] is not None
                        else 0.5
                    )

                    trend_analysis["combined"] = (adx_val * adx_weight) + (
                        of_val * of_weight
                    )
                    trend_strength = trend_analysis["combined"]

                    if self._tsl_log_count.get(symbol, 0) % 10 == 0:
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #6: Исправление форматирования f-string
                        adx_val = trend_analysis.get("adx")
                        adx_str = f"{adx_val:.2f}" if adx_val is not None else "N/A"
                        order_flow_val = trend_analysis.get("order_flow")
                        order_flow_str = (
                            f"{order_flow_val:.2f}"
                            if order_flow_val is not None
                            else "N/A"
                        )
                        logger.debug(
                            f"📊 Анализ силы тренда для {symbol}: "
                            f"ADX={adx_str}, "
                            f"OrderFlow={order_flow_str}, "
                            f"Combined={trend_analysis['combined']:.2f}"
                        )
            except Exception as e:
                logger.debug(f"⚠️ Не удалось получить trend_strength для {symbol}: {e}")

            try:
                if (
                    hasattr(self.signal_generator, "regime_manager")
                    and self.signal_generator.regime_manager
                ):
                    regime_obj = (
                        self.signal_generator.regime_manager.get_current_regime()
                    )
                    if regime_obj:
                        market_regime = (
                            regime_obj.lower() if isinstance(regime_obj, str) else None
                        )
            except Exception as e:
                logger.debug(f"Не удалось получить market_regime: {e}")

            if symbol not in self._tsl_log_count:
                self._tsl_log_count[symbol] = 0
            self._tsl_log_count[symbol] += 1

            if self._tsl_log_count[symbol] % 5 == 0:
                trend_str = (
                    f"{trend_strength:.2f}" if trend_strength is not None else "N/A"
                )
                regime_str = market_regime or "N/A"
                logger.info(
                    f"📊 TrailingSL {symbol}: price={current_price:.2f}, entry={entry_price:.2f}, "
                    f"{extremum_label}={extremum:.2f}, stop={stop_loss:.2f}, "
                    f"profit={profit_pct:.2%} (net), gross={profit_pct_gross:.2%}, "
                    f"trend={trend_str}, regime={regime_str}"
                )

            if not self._has_position(symbol):
                logger.debug(
                    f"⚠️ Позиция {symbol} уже закрыта или закрывается, пропускаем проверку TSL"
                )
                return

            # ✅ НОВОЕ (26.12.2025): Используем ExitDecisionCoordinator для координации закрытия
            exit_decision = None
            if self.exit_decision_coordinator:
                try:
                    # Получаем позицию и метаданные для координатора
                    position = self.get_position_callback(symbol)
                    metadata = None
                    if hasattr(self, "position_registry") and self.position_registry:
                        try:
                            metadata = await self.position_registry.get_metadata(symbol)
                        except Exception:
                            pass

                    current_price = await self.get_current_price_callback(symbol)
                    if current_price is None:
                        current_price = 0.0

                    # Получаем режим
                    regime = "ranging"
                    if self.signal_generator and hasattr(
                        self.signal_generator, "regime_managers"
                    ):
                        regime_manager = self.signal_generator.regime_managers.get(
                            symbol
                        )
                        if regime_manager:
                            regime = regime_manager.get_current_regime() or "ranging"

                    exit_decision = (
                        await self.exit_decision_coordinator.analyze_position(
                            symbol=symbol,
                            position=position,
                            metadata=metadata,
                            market_data=None,
                            current_price=current_price,
                            regime=regime,
                        )
                    )
                except Exception as e:
                    logger.debug(
                        f"⚠️ TrailingSLCoordinator: Ошибка вызова ExitDecisionCoordinator для {symbol}: {e}"
                    )
            elif self.exit_analyzer:
                # Fallback: используем ExitAnalyzer напрямую
                try:
                    exit_decision = await self.exit_analyzer.analyze_position(symbol)
                    if exit_decision:
                        action = exit_decision.get("action")
                        reason = exit_decision.get("reason", "exit_analyzer")
                        # ✅ ИСПРАВЛЕНИЕ: pnl_pct из ExitAnalyzer в процентах (0.5 = 0.5%)
                        # _calculate_pnl_percent возвращает проценты (0.5 = 0.5%)
                        # profit_pct из TSL в долях (0.005 = 0.5%), конвертируем для единообразия
                        decision_pnl_raw = exit_decision.get("pnl_pct")
                        if decision_pnl_raw is not None:
                            # pnl_pct из ExitAnalyzer в процентах (0.5 = 0.5%) -> в долю для единого форматирования
                            decision_pnl_frac = float(decision_pnl_raw) / 100.0
                        else:
                            # Fallback: profit_pct из TSL уже в долях
                            decision_pnl_frac = float(profit_pct or 0.0)

                        logger.info(
                            f"🎯 ExitAnalyzer решение для {symbol}: action={action}, "
                            f"reason={reason}, pnl={decision_pnl_frac:.2%}"
                        )

                        # Если ExitAnalyzer решил закрыть - закрываем сразу
                        if action == "close":
                            logger.info(
                                f"✅ ExitAnalyzer: Закрываем {symbol} (reason={reason}, pnl={decision_pnl_frac:.2%})"
                            )
                            if self._has_position(symbol):
                                await self.close_position_callback(symbol, reason)
                            return
                        # ✅ Если ExitAnalyzer решил частично закрыть - выполняем частичное закрытие
                        elif action == "partial_close":
                            fraction = exit_decision.get("fraction", 0.5)
                            logger.info(
                                f"📊 ExitAnalyzer: Частичное закрытие {symbol} ({fraction*100:.0f}%, reason={reason})"
                            )

                            # Выполняем частичное закрытие через position_manager
                            if self.position_manager and hasattr(
                                self.position_manager, "close_partial_position"
                            ):
                                try:
                                    partial_result = await self.position_manager.close_partial_position(
                                        symbol=symbol,
                                        fraction=fraction,
                                        reason=reason,
                                    )

                                    if partial_result and partial_result.get("success"):
                                        logger.info(
                                            f"✅ Частичное закрытие {symbol} выполнено: "
                                            f"закрыто {fraction*100:.0f}%, "
                                            f"PnL={partial_result.get('net_partial_pnl', 0):+.2f} USDT"
                                        )
                                        # После частичного закрытия продолжаем мониторинг оставшейся позиции
                                    else:
                                        logger.warning(
                                            f"⚠️ Не удалось выполнить частичное закрытие {symbol}: "
                                            f"{partial_result.get('error', 'неизвестная ошибка')}"
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"❌ Ошибка при частичном закрытии {symbol}: {e}",
                                        exc_info=True,
                                    )
                            else:
                                logger.warning(
                                    f"⚠️ PositionManager не доступен для частичного закрытия {symbol}"
                                )

                        # ✅ Если ExitAnalyzer решил продлить TP - обновляем параметры TSL
                        elif action == "extend_tp":
                            new_tp_percent = exit_decision.get("new_tp")
                            trend_strength_extend = exit_decision.get(
                                "trend_strength", 0.0
                            )

                            logger.info(
                                f"📈 ExitAnalyzer: Продлеваем TP для {symbol} "
                                f"(новый TP={new_tp_percent:.2f}%, trend_strength={trend_strength_extend:.2f}, reason={reason})"
                            )

                            # Обновляем параметры TSL для продления TP
                            if symbol in self.trailing_sl_by_symbol:
                                tsl = self.trailing_sl_by_symbol[symbol]

                                # Сохраняем оригинальный TP для отслеживания продления
                                if not hasattr(tsl, "original_tp_percent"):
                                    # Получаем оригинальный TP из конфига или метаданных
                                    original_tp = exit_decision.get(
                                        "original_tp", new_tp_percent
                                    )
                                    tsl.original_tp_percent = original_tp
                                    logger.debug(
                                        f"📌 Сохранили оригинальный TP для {symbol}: {original_tp:.2f}%"
                                    )

                                # Увеличиваем TP в метаданных TSL (используется для логирования и анализа)
                                tsl.extended_tp_percent = new_tp_percent
                                tsl.tp_extended_count = (
                                    getattr(tsl, "tp_extended_count", 0) + 1
                                )

                                logger.info(
                                    f"✅ TP продлен для {symbol}: {tsl.original_tp_percent:.2f}% → {new_tp_percent:.2f}% "
                                    f"(продлений: {tsl.tp_extended_count})"
                                )

                            # Продолжаем - TSL будет работать с новыми параметрами
                        # ✅ Если ExitAnalyzer вернул "hold" - просто продолжаем мониторинг
                        elif action == "hold":
                            hold_reason = exit_decision.get("reason", "hold")
                            logger.debug(
                                f"⏸️ ExitAnalyzer: Держим позицию {symbol} (reason={hold_reason})"
                            )
                            # Продолжаем мониторинг - не закрываем
                        # ✅ Если action не распознан - логируем и продолжаем
                        else:
                            logger.warning(
                                f"⚠️ ExitAnalyzer: Неизвестный action={action} для {symbol}, продолжаем мониторинг"
                            )
                except Exception as e:
                    logger.error(
                        f"❌ ExitAnalyzer: Ошибка анализа для {symbol}: {e}",
                        exc_info=True,
                    )

            should_close_by_sl, close_reason = tsl.should_close_position(
                current_price,
                trend_strength=trend_strength,
                market_regime=market_regime,
                margin_used=margin_used if margin_used and margin_used > 0 else None,
                unrealized_pnl=unrealized_pnl if unrealized_pnl is not None else None,
            )

            should_block_close = False
            if should_close_by_sl and profit_pct > 0:
                # ✅ ЭТАП 1.1: Анализ разворота Order Flow (приоритет 1)
                order_flow_reversal_detected = False
                if self.order_flow:
                    try:
                        current_delta = self.order_flow.get_delta()
                        avg_delta = self.order_flow.get_avg_delta(periods=10)

                        # Сохраняем историю delta для анализа разворота
                        if symbol not in self._order_flow_delta_history:
                            self._order_flow_delta_history[symbol] = []
                        self._order_flow_delta_history[symbol].append(
                            (time.time(), current_delta)
                        )
                        # Храним историю за последние 5 минут
                        cutoff_time = time.time() - 300
                        self._order_flow_delta_history[symbol] = [
                            (t, d)
                            for t, d in self._order_flow_delta_history[symbol]
                            if t > cutoff_time
                        ]

                        # Получаем параметры из конфига
                        reversal_config = getattr(
                            self.scalping_config, "position_manager", {}
                        ).get("reversal_detection", {})
                        order_flow_config = reversal_config.get("order_flow", {})
                        enabled = order_flow_config.get("enabled", True)
                        reversal_threshold = order_flow_config.get(
                            "reversal_threshold", 0.15
                        )  # 15% изменение delta

                        if enabled and len(self._order_flow_delta_history[symbol]) >= 2:
                            # Анализируем изменение delta за последние периоды
                            recent_deltas = [
                                d
                                for _, d in self._order_flow_delta_history[symbol][-10:]
                            ]
                            if len(recent_deltas) >= 2:
                                # Проверяем разворот: для LONG позиции delta должен был быть положительным и стать отрицательным
                                if position_side.lower() == "long":
                                    # Для LONG: разворот = delta был > threshold и стал < -threshold
                                    prev_delta = (
                                        recent_deltas[-2]
                                        if len(recent_deltas) >= 2
                                        else avg_delta
                                    )
                                    if (
                                        prev_delta > reversal_threshold
                                        and current_delta < -reversal_threshold
                                    ):
                                        order_flow_reversal_detected = True
                                        logger.info(
                                            f"🔄 Order Flow разворот обнаружен для {symbol} LONG: "
                                            f"delta {prev_delta:.3f} → {current_delta:.3f} "
                                            f"(покупатели → продавцы, закрываем позицию)"
                                        )
                                elif position_side.lower() == "short":
                                    # Для SHORT: разворот = delta был < -threshold и стал > threshold
                                    prev_delta = (
                                        recent_deltas[-2]
                                        if len(recent_deltas) >= 2
                                        else avg_delta
                                    )
                                    if (
                                        prev_delta < -reversal_threshold
                                        and current_delta > reversal_threshold
                                    ):
                                        order_flow_reversal_detected = True
                                        logger.info(
                                            f"🔄 Order Flow разворот обнаружен для {symbol} SHORT: "
                                            f"delta {prev_delta:.3f} → {current_delta:.3f} "
                                            f"(продавцы → покупатели, закрываем позицию)"
                                        )
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка анализа Order Flow разворота для {symbol}: {e}"
                        )

                # Если Order Flow показывает разворот - закрываем позицию (не блокируем)
                if order_flow_reversal_detected:
                    logger.info(
                        f"🔄 Закрываем {symbol} по Order Flow развороту "
                        f"(profit={profit_pct:.2%}, delta изменился)"
                    )
                    if self.debug_logger:
                        entry_time = position.get("entry_time")
                        if isinstance(entry_time, datetime):
                            # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                            if entry_time.tzinfo is None:
                                entry_time = entry_time.replace(tzinfo=timezone.utc)
                            elif entry_time.tzinfo != timezone.utc:
                                entry_time = entry_time.astimezone(timezone.utc)
                            minutes_in_position = (
                                datetime.now(timezone.utc) - entry_time
                            ).total_seconds() / 60.0
                        elif tsl.entry_timestamp > 0:
                            minutes_in_position = (
                                time.time() - tsl.entry_timestamp
                            ) / 60.0
                        else:
                            minutes_in_position = 0.0
                        self.debug_logger.log_position_close(
                            symbol=symbol,
                            exit_price=current_price,
                            # profit_pct здесь в долях (0.005 = 0.5% от маржи)
                            pnl_usd=(profit_pct * float(position.get("margin", 0)))
                            if position.get("margin")
                            else 0.0,
                            pnl_pct=profit_pct,
                            time_in_position_minutes=minutes_in_position,
                            reason="order_flow_reversal",
                        )
                    if self._has_position(symbol):
                        await self.close_position_callback(
                            symbol, "order_flow_reversal"
                        )
                    return

                reversal_config = getattr(
                    self.scalping_config, "position_manager", {}
                ).get("reversal_detection", {})

                if reversal_config.get("enabled", False):
                    try:
                        pos_side = position_side

                        if hasattr(self.signal_generator, "_get_market_data"):
                            market_data = await self.signal_generator._get_market_data(
                                symbol
                            )
                        else:
                            market_data = None
                        if market_data and getattr(market_data, "ohlcv_data", None):
                            indicators = (
                                self.signal_generator.indicator_manager.calculate_all(
                                    market_data
                                )
                            )

                            if reversal_config.get("rsi_check", True):
                                rsi_result = indicators.get("RSI") or indicators.get(
                                    "rsi"
                                )
                                if rsi_result:
                                    rsi_value = (
                                        rsi_result.value
                                        if hasattr(rsi_result, "value")
                                        else rsi_result
                                    )
                                    if pos_side == "long" and rsi_value < 30:
                                        logger.debug(
                                            f"📊 RSI перепродан ({rsi_value:.1f}) для {symbol} LONG - "
                                            f"блокируем закрытие по trailing stop (позиция в прибыли)"
                                        )
                                        should_block_close = True
                                    if pos_side == "short" and rsi_value > 70:
                                        logger.debug(
                                            f"📊 RSI перекуплен ({rsi_value:.1f}) для {symbol} SHORT - "
                                            f"блокируем закрытие по trailing stop (позиция в прибыли)"
                                        )
                                        should_block_close = True

                            if (
                                reversal_config.get("macd_check", True)
                                and not should_block_close
                            ):
                                macd_result = indicators.get("MACD") or indicators.get(
                                    "macd"
                                )
                                if macd_result and hasattr(macd_result, "metadata"):
                                    macd_line = macd_result.metadata.get("macd_line", 0)
                                    signal_line = macd_result.metadata.get(
                                        "signal_line", 0
                                    )
                                    histogram = macd_line - signal_line

                                    if pos_side == "long" and histogram > 0:
                                        logger.debug(
                                            f"📊 MACD бычья дивергенция для {symbol} LONG - "
                                            f"блокируем закрытие по trailing stop (позиция в прибыли)"
                                        )
                                        should_block_close = True

                                    if pos_side == "short" and histogram < 0:
                                        logger.debug(
                                            f"📊 MACD медвежья дивергенция для {symbol} SHORT - "
                                            f"блокируем закрытие по trailing stop (позиция в прибыли)"
                                        )
                                        should_block_close = True

                            if (
                                reversal_config.get("bollinger_check", True)
                                and not should_block_close
                            ):
                                bb_result = indicators.get(
                                    "BollingerBands"
                                ) or indicators.get("bollinger_bands")
                                if bb_result and hasattr(bb_result, "metadata"):
                                    upper = bb_result.metadata.get(
                                        "upper_band", current_price
                                    )
                                    lower = bb_result.metadata.get(
                                        "lower_band", current_price
                                    )
                                    middle = (
                                        bb_result.value
                                        if hasattr(bb_result, "value")
                                        else current_price
                                    )

                                    if (
                                        pos_side == "long"
                                        and current_price <= lower * 1.001
                                    ):
                                        logger.debug(
                                            f"📊 Цена у нижней полосы Bollinger для {symbol} LONG - "
                                            f"блокируем закрытие по trailing stop (позиция в прибыли)"
                                        )
                                        should_block_close = True

                                    if (
                                        pos_side == "short"
                                        and current_price >= upper * 0.999
                                    ):
                                        logger.debug(
                                            f"📊 Цена у верхней полосы Bollinger для {symbol} SHORT - "
                                            f"блокируем закрытие по trailing stop (позиция в прибыли)"
                                        )
                                        should_block_close = True
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки индикаторов для {symbol}: {e}"
                        )

            if should_close_by_sl:
                if should_block_close:
                    logger.debug(
                        f"🔒 Закрытие по trailing stop заблокировано для {symbol} "
                        f"(индикаторы показывают возможный разворот в нашу пользу, позиция в прибыли)"
                    )
                    return

                trend_str_close = (
                    f"{trend_strength:.2f}" if trend_strength is not None else "N/A"
                )
                comparison_op = ">=" if position_side.lower() == "short" else "<="
                entry_time = position.get("entry_time")
                if isinstance(entry_time, datetime):
                    minutes_in_position = (
                        datetime.now() - entry_time
                    ).total_seconds() / 60.0
                elif tsl.entry_timestamp > 0:
                    minutes_in_position = (time.time() - tsl.entry_timestamp) / 60.0
                else:
                    minutes_in_position = 0.0
                reason_str = close_reason or "trailing_stop"
                logger.info(
                    f"📊 Закрываем {symbol} по причине: {reason_str} "
                    f"(price={current_price:.2f} {comparison_op} stop={stop_loss:.2f}, "
                    f"profit={profit_pct:.2%}, time={minutes_in_position:.2f} мин, trend={trend_str_close})"
                )
                if self.debug_logger:
                    self.debug_logger.log_position_close(
                        symbol=symbol,
                        exit_price=current_price,
                        # profit_pct здесь в долях (0.005 = 0.5% от маржи)
                        pnl_usd=(profit_pct * float(position.get("margin", 0)))
                        if position.get("margin")
                        else 0.0,
                        pnl_pct=profit_pct,
                        time_in_position_minutes=minutes_in_position,
                        reason=reason_str,
                    )
                if self._has_position(symbol):
                    await self.close_position_callback(symbol, reason_str)
                else:
                    logger.debug(
                        f"⚠️ Позиция {symbol} уже была закрыта, пропускаем закрытие"
                    )
                return

            if self.position_manager:
                position_data = position
                if position_data:
                    entry_time = position_data.get("entry_time")
                    if isinstance(entry_time, datetime):
                        entry_time_ms = int(entry_time.timestamp() * 1000)
                    elif entry_time:
                        entry_time_ms = (
                            int(float(entry_time) * 1000)
                            if float(entry_time) < 1000000000000
                            else int(entry_time)
                        )
                    else:
                        entry_time_ms = ""

                    position_dict = {
                        "instId": f"{symbol}-SWAP",
                        "pos": str(
                            position_data.get("size", position_data.get("pos", "0"))
                            or "0"
                        ),
                        "posSide": position_data.get(
                            "position_side", position_data.get("posSide", "long")
                        ),
                        "avgPx": str(entry_price),
                        "markPx": str(current_price),
                        "cTime": str(entry_time_ms) if entry_time_ms else "",
                    }

                    ph_should_close = (
                        await self.position_manager._check_profit_harvesting(
                            position_dict
                        )
                    )
                    if ph_should_close:
                        logger.info(
                            f"💰 PH сработал для {symbol} - закрываем позицию немедленно!"
                        )
                        await self.close_position_callback(symbol, "profit_harvest")
                        return

            await self._check_position_holding_time(
                symbol, current_price, profit_pct, market_regime
            )

        except Exception as e:
            logger.error(f"Ошибка обновления трейлинг стоп-лосса: {e}")

    async def periodic_check(self):
        """
        Периодическая проверка Trailing Stop Loss для всех позиций с адаптивным интервалом.
        """
        try:
            has_active_positions = bool(
                self.active_positions_ref and len(self.active_positions_ref) > 0
            )
            if not self.trailing_sl_by_symbol and not has_active_positions:
                return

            current_time = time.time()

            current_regime = "ranging"
            try:
                if (
                    hasattr(self.signal_generator, "regime_manager")
                    and self.signal_generator.regime_manager
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
            except Exception:
                pass

            check_interval = self._tsl_check_interval
            if current_regime in self._tsl_check_intervals_by_regime:
                check_interval = self._tsl_check_intervals_by_regime[current_regime]
            else:
                try:
                    tsl_config = getattr(self.scalping_config, "trailing_sl", {})
                    by_regime = getattr(tsl_config, "by_regime", None)
                    if by_regime:
                        regime_config = getattr(by_regime, current_regime, None)
                        if regime_config:
                            regime_interval = getattr(
                                regime_config, "check_interval_seconds", None
                            )
                            if regime_interval:
                                check_interval = float(regime_interval)
                                self._tsl_check_intervals_by_regime[
                                    current_regime
                                ] = check_interval
                except Exception:
                    pass

            symbols_to_check = list(self.trailing_sl_by_symbol.keys())
            if self.active_positions_ref:
                for symbol in self.active_positions_ref.keys():
                    if symbol not in symbols_to_check:
                        symbols_to_check.append(symbol)

            if not symbols_to_check:
                return

            for symbol in symbols_to_check:
                try:
                    last_check = self._last_tsl_check_time.get(symbol, 0.0)
                    if current_time - last_check < check_interval:
                        continue
                    self._last_tsl_check_time[symbol] = current_time

                    current_price = await self._get_current_price(symbol)
                    if current_price and current_price > 0:
                        await self.update_trailing_stop_loss(symbol, current_price)
                    else:
                        logger.debug(
                            f"⚠️ Не удалось получить цену для {symbol} при периодической проверке TSL"
                        )
                except Exception as e:
                    logger.debug(
                        f"⚠️ Ошибка периодической проверки TSL для {symbol}: {e}"
                    )
        except Exception as e:
            logger.error(f"❌ Ошибка в periodic_check: {e}")

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Получение текущей цены через внешний колбэк или REST fallback.
        """
        if self.get_current_price_callback:
            try:
                price = await self.get_current_price_callback(symbol)
                if price:
                    return price
            except TypeError:
                # На случай если передана синхронная функция
                price = self.get_current_price_callback(symbol)
                if price:
                    return price
            except Exception as e:
                logger.debug(
                    f"⚠️ Колбэк получения цены вернул ошибку для {symbol}: {e}, используем fallback"
                )

        return await self._fetch_price_via_client(symbol)

    async def _fetch_price_via_client(self, symbol: str) -> Optional[float]:
        """
        Получение текущей цены через публичный REST endpoint OKX.
        """
        try:
            import aiohttp

            inst_id = f"{symbol}-SWAP"
            base_url = "https://www.okx.com"
            ticker_url = f"{base_url}/api/v5/market/ticker?instId={inst_id}"

            session = (
                self.client.session
                if getattr(self.client, "session", None)
                and not self.client.session.closed
                else None
            )
            if not session:
                session = aiohttp.ClientSession()
                close_session = True
            else:
                close_session = False

            try:
                async with session.get(ticker_url) as ticker_resp:
                    if ticker_resp.status == 200:
                        ticker_data = await ticker_resp.json()
                        if ticker_data and ticker_data.get("code") == "0":
                            data = ticker_data.get("data", [])
                            if data:
                                last_price = data[0].get("last")
                                if last_price:
                                    return float(last_price)
                    else:
                        logger.debug(
                            f"⚠️ Не удалось получить цену для {symbol}: HTTP {ticker_resp.status}"
                        )
            finally:
                if close_session and session:
                    await session.close()

            logger.debug(f"⚠️ Не удалось получить цену для {symbol} через REST API")
            return None

        except Exception as e:
            logger.debug(f"⚠️ Ошибка получения цены для {symbol}: {e}")
            return None

    async def _check_position_holding_time(
        self,
        symbol: str,
        current_price: float,
        profit_pct: float,
        market_regime: Optional[str] = None,
    ):
        """Проверка времени жизни позиции с продлением для прибыльных сделок."""
        try:
            position = self._get_position(symbol)
            if not position:
                return

            entry_time = position.get("entry_time") or position.get("timestamp")
            if not entry_time:
                logger.debug(
                    f"⚠️ Нет времени открытия для позиции {symbol} "
                    f"(entry_time будет установлен при инициализации TSL)"
                )
                return

            if isinstance(entry_time, datetime):
                # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                elif entry_time.tzinfo != timezone.utc:
                    entry_time = entry_time.astimezone(timezone.utc)
                time_held = (
                    datetime.now(timezone.utc) - entry_time
                ).total_seconds() / 60.0
            else:
                logger.debug(
                    f"⚠️ Неверный формат entry_time для {symbol}: {entry_time}"
                )
                return

            max_holding_minutes = 30.0
            extend_time_if_profitable = True
            min_profit_for_extension = 0.1
            extension_percent = 50.0

            try:
                if (
                    hasattr(self.signal_generator, "regime_manager")
                    and self.signal_generator.regime_manager
                ):
                    regime_obj = (
                        self.signal_generator.regime_manager.get_current_regime()
                        if not market_regime
                        else market_regime
                    )
                    if isinstance(regime_obj, str):
                        regime_obj = regime_obj.lower()

                    regime_params = (
                        self.signal_generator.regime_manager.get_current_parameters()
                    )
                    if regime_params:
                        max_holding_minutes = float(
                            getattr(regime_params, "max_holding_minutes", 30.0)
                        )

                    regime_name = (
                        regime_obj
                        if isinstance(regime_obj, str)
                        else getattr(regime_obj, "value", "ranging").lower()
                    )
                    adaptive_regime_cfg = getattr(
                        getattr(self.scalping_config, "adaptive_regime", None),
                        regime_name,
                        None,
                    )
                    if adaptive_regime_cfg:
                        extend_time_if_profitable = bool(
                            getattr(
                                adaptive_regime_cfg, "extend_time_if_profitable", True
                            )
                        )
                        min_profit_for_extension = float(
                            getattr(
                                adaptive_regime_cfg, "min_profit_for_extension", 0.1
                            )
                        )
                        extension_percent = float(
                            getattr(adaptive_regime_cfg, "extension_percent", 50.0)
                        )
            except Exception as e:
                logger.debug(
                    f"Не удалось получить параметры режима: {e}, используем fallback"
                )

            actual_max_holding = float(
                position.get("max_holding_minutes", max_holding_minutes)
            )

            if time_held >= actual_max_holding:
                time_extended = position.get("time_extended", False)
                # ✅ ИСПРАВЛЕНО: Проверяем продление ВАЖНЕЕ чем закрытие
                if (
                    extend_time_if_profitable
                    and not time_extended
                    and profit_pct
                    >= min_profit_for_extension  # ✅ ИСПРАВЛЕНО: >= вместо > (0.44% >= 0.5% = false, но это правильно, нужно >= 0.5%)
                ):
                    original_max_holding = max_holding_minutes
                    extension_minutes = original_max_holding * (
                        extension_percent / 100.0
                    )
                    new_max_holding = original_max_holding + extension_minutes
                    position["time_extended"] = True
                    position["max_holding_minutes"] = new_max_holding
                    # ✅ Обновляем также в orchestrator.active_positions для синхронизации
                    if hasattr(self, "orchestrator") and self.orchestrator:
                        if symbol in self.orchestrator.active_positions:
                            self.orchestrator.active_positions[symbol][
                                "time_extended"
                            ] = True
                            self.orchestrator.active_positions[symbol][
                                "max_holding_minutes"
                            ] = new_max_holding
                    logger.info(
                        f"✅ Позиция {symbol} в прибыли {profit_pct:.2%} "
                        f"(>={min_profit_for_extension:.2%}), продлеваем время на "
                        f"{extension_minutes:.1f} минут (с {original_max_holding:.1f} до {new_max_holding:.1f} минут)"
                    )
                    return

                # ✅ ИСПРАВЛЕНО: Не закрываем по max_holding если прибыль > min_profit_to_close
                # Бот продолжает искать оптимальный момент закрытия через TP/SL
                min_profit_to_close = None
                tsl = self.trailing_sl_by_symbol.get(symbol)
                if tsl:
                    min_profit_to_close = getattr(tsl, "min_profit_to_close", None)

                if (
                    min_profit_to_close is not None
                    and profit_pct >= min_profit_to_close
                ):
                    logger.info(
                        f"✅ Позиция {symbol} удерживается {time_held:.1f} минут "
                        f"(лимит: {actual_max_holding:.1f} минут), "
                        f"прибыль {profit_pct:.2%} >= min_profit_to_close {min_profit_to_close:.2%}, "
                        f"не закрываем по max_holding (бот продолжает искать оптимальный момент через TP/SL)"
                    )
                    return

                # ✅ ИСПРАВЛЕНО: Убыточные позиции НЕ закрываем по времени (ждем TP/SL или разворота)
                if profit_pct <= 0:
                    logger.info(
                        f"⏰ Позиция {symbol} удерживается {time_held:.1f} минут "
                        f"(лимит: {actual_max_holding:.1f} минут), "
                        f"прибыль {profit_pct:.2%} <= 0%, НЕ закрываем по времени (ждем TP/SL)"
                    )
                    return

                # ✅ ИСПРАВЛЕНО: Закрываем ТОЛЬКО если прибыль мала (< min_profit_for_extension) И время вышло
                if profit_pct < min_profit_for_extension:
                    logger.warning(
                        f"⏰ Позиция {symbol} удерживается {time_held:.1f} минут "
                        f"(лимит: {actual_max_holding:.1f} минут), "
                        f"прибыль {profit_pct:.2%} < {min_profit_for_extension:.2%} (min для продления), закрываем по времени"
                    )
                    await self.close_position_callback(symbol, "max_holding_time")
                else:
                    # ✅ Если прибыль >= min_profit_for_extension, но не продлеваем (возможно, уже продлена)
                    # Используем trailing stop вместо закрытия по времени
                    logger.info(
                        f"✅ Позиция {symbol} удерживается {time_held:.1f} минут "
                        f"(лимит: {actual_max_holding:.1f} минут), "
                        f"прибыль {profit_pct:.2%} >= {min_profit_for_extension:.2%}, НЕ закрываем (используем trailing stop)"
                    )
                    return

        except Exception as e:
            logger.error(f"Ошибка проверки времени жизни позиции {symbol}: {e}")

    def get_tsl(self, symbol: str) -> Optional[TrailingStopLoss]:
        """Возвращает TSL для символа."""
        return self.trailing_sl_by_symbol.get(symbol)

    def remove_tsl(self, symbol: str) -> Optional[TrailingStopLoss]:
        """Удаляет TSL для символа и возвращает его."""
        tsl = self.trailing_sl_by_symbol.pop(symbol, None)
        if tsl:
            logger.debug(f"✅ TSL удален для {symbol}")
        return tsl

    def clear_all_tsl(self) -> int:
        """Очищает все TSL и возвращает количество удаленных записей."""
        count = len(self.trailing_sl_by_symbol)
        self.trailing_sl_by_symbol.clear()
        logger.info(f"✅ Очищено {count} TSL")
        return count
