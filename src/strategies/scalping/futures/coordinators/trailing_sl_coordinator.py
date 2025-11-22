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
from datetime import datetime
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
        get_position_callback: Callable[[str], Dict[str, Any]],  # Синхронная функция для получения позиции
        close_position_callback: Callable[[str, str], Awaitable[None]],  # Async функция для закрытия позиции
        get_current_price_callback: Callable[[str], Awaitable[Optional[float]]],  # Async функция для получения цены
        active_positions_ref: Optional[Dict[str, Dict[str, Any]]] = None,  # Ссылка на active_positions (опционально)
        fast_adx=None,
        position_manager=None,
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
        """
        self.config_manager = config_manager
        self.debug_logger = debug_logger
        self.signal_generator = signal_generator
        self.client = client
        self.scalping_config = scalping_config
        self.get_position_callback = get_position_callback
        self.close_position_callback = close_position_callback
        self.get_current_price_callback = get_current_price_callback
        self.active_positions_ref = active_positions_ref  # Для прямого доступа к active_positions
        self.fast_adx = fast_adx
        self.position_manager = position_manager

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
        impulse_trailing = None
        if signal and signal.get("is_impulse"):
            impulse_trailing = signal.get("impulse_trailing") or {}
            if impulse_trailing:
                params["initial_trail"] = impulse_trailing.get(
                    "initial_trail", params["initial_trail"]
                )

        # Сбрасываем предыдущий экземпляр, если он был
        existing_tsl = self.trailing_sl_by_symbol.get(symbol)
        if existing_tsl:
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

        # ✅ ЭТАП 4.4: Инициализируем с правильной стороной (long/short)
        tsl.initialize(entry_price=entry_price, side=position_side, symbol=symbol)
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
            tsl.update(current_price)
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
                timeout=params.get("timeout_minutes")
            )

        # ✅ DEBUG LOGGER: Логируем загруженные параметры конфига
        if self.debug_logger:
            self.debug_logger.log_config_loaded(
                symbol=symbol,
                regime=regime or "unknown",
                params=params
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
                        logger.debug(
                            f"⚠️ Entry price = 0 для {symbol}, avgPx={avg_px}, пропускаем обновление TSL (будет восстановлено при следующем WebSocket обновлении)"
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
                    pos_side = position.get("posSide") or position.get("position_side", "long")

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
                                    position["entry_time"] = datetime.fromtimestamp(entry_timestamp)
                                    position["timestamp"] = position["entry_time"]
                                    logger.debug(
                                        f"✅ Установлен entry_time для {symbol} из cTime/uTime: {position['entry_time']}"
                                    )
                                except (ValueError, TypeError) as e:
                                    logger.warning(
                                        f"⚠️ Не удалось распарсить cTime/uTime для {symbol}: {e}, используем текущее время"
                                    )
                                    position["entry_time"] = datetime.now()
                                    position["timestamp"] = position["entry_time"]
                            else:
                                position["entry_time"] = datetime.now()
                                position["timestamp"] = position["entry_time"]
                                logger.debug(
                                    f"⚠️ entry_time не найден для {symbol}, используем текущее время"
                                )

                        tsl = self.initialize_trailing_stop(
                            symbol=symbol,
                            entry_price=entry_price,
                            side=pos_side,
                            current_price=current_price,
                            signal=None,
                        )

                        if tsl:
                            logger.info(
                                f"✅ TrailingStopLoss автоматически инициализирован для {symbol} "
                                f"(entry={entry_price:.5f}, side={pos_side}, size={pos_size}, "
                                f"entry_time={position.get('entry_time', 'N/A')})"
                            )
                        else:
                            logger.error(f"❌ Не удалось инициализировать TSL для {symbol}")
                            return
                    else:
                        logger.warning(
                            f"⚠️ Недостаточно данных для инициализации TSL для {symbol}: "
                            f"entry_price={entry_price}, size={pos_size}"
                        )
                        return
                except Exception as e:
                    logger.error(f"❌ Ошибка автоматической инициализации TSL для {symbol}: {e}")
                    return

                if symbol not in self.trailing_sl_by_symbol:
                    logger.error(
                        f"❌ TSL для {symbol} не инициализирован после попытки автоматической инициализации"
                    )
                    return

            tsl = self.trailing_sl_by_symbol[symbol]
            tsl.update(current_price)

            stop_loss = tsl.get_stop_loss()
            profit_pct = tsl.get_profit_pct(current_price, include_fees=True)
            profit_pct_gross = tsl.get_profit_pct(current_price, include_fees=False)

            position_side = position.get("position_side", position.get("posSide", "long"))
            if position_side.lower() == "short":
                extremum = tsl.lowest_price
                extremum_label = "lowest"
            else:
                extremum = tsl.highest_price
                extremum_label = "highest"

            trend_strength = None
            market_regime = None

            try:
                if self.fast_adx:
                    adx_value = self.fast_adx.get_current_adx()
                    if adx_value and adx_value > 0:
                        trend_strength = min(adx_value / 100.0, 1.0)
            except Exception as e:
                logger.debug(f"Не удалось получить trend_strength: {e}")

            try:
                if (
                    hasattr(self.signal_generator, "regime_manager")
                    and self.signal_generator.regime_manager
                ):
                    regime_obj = self.signal_generator.regime_manager.get_current_regime()
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
                trend_str = f"{trend_strength:.2f}" if trend_strength is not None else "N/A"
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

            should_close_by_sl, close_reason = tsl.should_close_position(
                current_price,
                trend_strength=trend_strength,
                market_regime=market_regime,
            )

            should_block_close = False
            if should_close_by_sl and profit_pct > 0:
                reversal_config = getattr(
                    self.scalping_config, "position_manager", {}
                ).get("reversal_detection", {})

                if reversal_config.get("enabled", False):
                    try:
                        pos_side = position_side

                        if hasattr(self.signal_generator, "_get_market_data"):
                            market_data = await self.signal_generator._get_market_data(symbol)
                        else:
                            market_data = None
                        if market_data and getattr(market_data, "ohlcv_data", None):
                            indicators = self.signal_generator.indicator_manager.calculate_all(
                                market_data
                            )

                            if reversal_config.get("rsi_check", True):
                                rsi_result = indicators.get("RSI") or indicators.get("rsi")
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
                                macd_result = indicators.get("MACD") or indicators.get("macd")
                                if macd_result and hasattr(macd_result, "metadata"):
                                    macd_line = macd_result.metadata.get("macd_line", 0)
                                    signal_line = macd_result.metadata.get("signal_line", 0)
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
                                bb_result = indicators.get("BollingerBands") or indicators.get(
                                    "bollinger_bands"
                                )
                                if bb_result and hasattr(bb_result, "metadata"):
                                    upper = bb_result.metadata.get("upper_band", current_price)
                                    lower = bb_result.metadata.get("lower_band", current_price)
                                    middle = (
                                        bb_result.value
                                        if hasattr(bb_result, "value")
                                        else current_price
                                    )

                                    if pos_side == "long" and current_price <= lower * 1.001:
                                        logger.debug(
                                            f"📊 Цена у нижней полосы Bollinger для {symbol} LONG - "
                                            f"блокируем закрытие по trailing stop (позиция в прибыли)"
                                        )
                                        should_block_close = True

                                    if pos_side == "short" and current_price >= upper * 0.999:
                                        logger.debug(
                                            f"📊 Цена у верхней полосы Bollinger для {symbol} SHORT - "
                                            f"блокируем закрытие по trailing stop (позиция в прибыли)"
                                        )
                                        should_block_close = True
                    except Exception as e:
                        logger.debug(f"⚠️ Ошибка проверки индикаторов для {symbol}: {e}")

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
                    minutes_in_position = (datetime.now() - entry_time).total_seconds() / 60.0
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
                        pnl_usd=profit_pct * position.get("margin", 0) / 100.0
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
                            position_data.get("size", position_data.get("pos", "0")) or "0"
                        ),
                        "posSide": position_data.get("position_side", position_data.get("posSide", "long")),
                        "avgPx": str(entry_price),
                        "markPx": str(current_price),
                        "cTime": str(entry_time_ms) if entry_time_ms else "",
                    }

                    ph_should_close = await self.position_manager._check_profit_harvesting(
                        position_dict
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
                    regime_obj = self.signal_generator.regime_manager.get_current_regime()
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
                time_held = (datetime.now() - entry_time).total_seconds() / 60.0
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
                if (
                    extend_time_if_profitable
                    and not time_extended
                    and profit_pct > min_profit_for_extension
                ):
                    original_max_holding = max_holding_minutes
                    extension_minutes = original_max_holding * (
                        extension_percent / 100.0
                    )
                    new_max_holding = original_max_holding + extension_minutes
                    position["time_extended"] = True
                    position["max_holding_minutes"] = new_max_holding
                    logger.info(
                        f"⏰ Позиция {symbol} в прибыли {profit_pct:.2%} "
                        f"(>{min_profit_for_extension:.2%}), продлеваем время на "
                        f"{extension_minutes:.1f} минут (до {new_max_holding:.1f})"
                    )
                    return

                min_profit_to_close = None
                tsl = self.trailing_sl_by_symbol.get(symbol)
                if tsl:
                    min_profit_to_close = getattr(tsl, "min_profit_to_close", None)

                if (
                    min_profit_to_close is not None
                    and profit_pct > min_profit_to_close
                ):
                    logger.info(
                        f"⏰ Позиция {symbol} удерживается {time_held:.1f} минут "
                        f"(лимит: {actual_max_holding:.1f} минут), "
                        f"но прибыль {profit_pct:.2%} > min_profit_to_close "
                        f"{min_profit_to_close:.2%}, не закрываем"
                    )
                    return

                if profit_pct <= 0:
                    logger.info(
                        f"⏰ Позиция {symbol} удерживается {time_held:.1f} минут "
                        f"(лимит: {actual_max_holding:.1f} минут), "
                        f"прибыль {profit_pct:.2%} <= 0%, не закрываем по времени"
                    )
                    return

                logger.info(
                    f"⏰ Позиция {symbol} удерживается {time_held:.1f} минут "
                    f"(лимит: {actual_max_holding:.1f} минут), "
                    f"прибыль: {profit_pct:.2%}, закрываем по времени"
                )
                await self.close_position_callback(symbol, "max_holding_time")

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
