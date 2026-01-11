"""
Parameter Provider - Единая точка получения параметров торговли.

Обеспечивает централизованный доступ к параметрам из различных источников:
    def _apply_adaptive_exit_params(
        self,
        base_params: Dict[str, Any],
        symbol: str,
        regime: Optional[str],
                    "max_holding_minutes",
                    {
                        "ranging": 25.0,
                        "trending": 15.0,  # ✅ ИСПРАВЛЕНИЕ #3 (07.01.2026): Правильный default для trending
                        "choppy": 10.0,  # ✅ ИСПРАВЛЕНИЕ #3 (07.01.2026): Правильный default для choppy
                    }.get(
                        regime.lower() if regime else "ranging", 25.0
                    ),  # Fallback на ranging если режим не определён
                )
                exit_params["sl_atr_multiplier"] = _to_float(
                    exit_params.get("sl_atr_multiplier"),
                    "sl_atr_multiplier",
                    2.0,  # ✅ Default увеличен с 1.5 до 2.0
                )
                exit_params["tp_atr_multiplier"] = _to_float(
                    exit_params.get("tp_atr_multiplier"), "tp_atr_multiplier", 1.0
                )
                exit_params["min_profit_for_extension"] = _to_float(
                    exit_params.get("min_profit_for_extension"),
                    "min_profit_for_extension",
                    0.4,
                )
                exit_params["extension_percent"] = _to_float(
                    exit_params.get("extension_percent"), "extension_percent", 100.0
                )
                exit_params["min_holding_minutes"] = _to_float(
                    exit_params.get("min_holding_minutes"),
                    "min_holding_minutes",
                    0.5,  # ✅ Default для ranging: 0.5 минуты
                )

            # ✅ ПРИОРИТЕТ 1 (29.12.2025): Проверка by_symbol для per-symbol параметров
            # ✅ НОВОЕ (03.01.2026): Логирование источников параметров для понимания работы бота
            sources_log = []
            if symbol and hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                by_symbol = config_dict.get("by_symbol", {})
                symbol_config = by_symbol.get(symbol, {})
                if isinstance(symbol_config, dict):
                    # Переопределяем параметры из by_symbol (приоритет выше exit_params.{regime})
                    per_symbol_keys = [
                        "sl_atr_multiplier",
                        "tp_atr_multiplier",
                        "max_holding_minutes",
                    ]
                    def _apply_adaptive_exit_params(
                        self,
                        base_params: Dict[str, Any],
                        symbol: str,
                        regime: Optional[str],
                        balance: Optional[float],
                        current_pnl: Optional[float],
                        drawdown: Optional[float],
                    ) -> Dict[str, Any]:
                        """Единая адаптация TP/SL по балансу, PnL и просадке."""

                        adaptive_config = self._get_adaptive_exit_config()
                        if not adaptive_config.get("enabled", False):
                            return base_params

                        params = base_params.copy()
                        adaptations_log: list[str] = []

                        # 1) Баланс
                        if balance is not None:
                            balance_adapt = self._adapt_by_balance(balance, params)
                            if balance_adapt:
                                params.update(balance_adapt)
                                adaptations_log.append(
                                    f"balance tp={balance_adapt.get('tp_atr_multiplier', 'N/A')} sl={balance_adapt.get('sl_atr_multiplier', 'N/A')}"
                                )

                        # 2) PnL
                        if current_pnl is not None:
                            pnl_adapt = self._adapt_tp_by_pnl(current_pnl, params)
                            if pnl_adapt:
                                old_tp = params.get("tp_atr_multiplier")
                                params.update(pnl_adapt)
                                new_tp = params.get("tp_atr_multiplier")
                                old_tp_str = f"{old_tp:.2f}" if isinstance(old_tp, (int, float)) else "0"
                                new_tp_str = f"{new_tp:.2f}" if isinstance(new_tp, (int, float)) else "0"
                                adaptations_log.append(
                                    f"pnl tp {old_tp_str}->{new_tp_str} ({current_pnl:.2f}%)"
                                )

                        # 3) Drawdown
                        if drawdown is not None:
                            dd_adapt = self._adapt_sl_by_drawdown(drawdown, params)
                            if dd_adapt:
                                old_sl = params.get("sl_atr_multiplier")
                                params.update(dd_adapt)
                                new_sl = params.get("sl_atr_multiplier")
                                old_sl_str = f"{old_sl:.2f}" if isinstance(old_sl, (int, float)) else "0"
                                new_sl_str = f"{new_sl:.2f}" if isinstance(new_sl, (int, float)) else "0"
                                adaptations_log.append(
                                    f"dd sl {old_sl_str}->{new_sl_str} ({drawdown:.2f}%)"
                                )

                        if adaptations_log:
                            logger.debug(
                                f"[ADAPTIVE_EXIT] {symbol} regime={regime or 'n/a'} | "
                                f"tp={params.get('tp_atr_multiplier')} sl={params.get('sl_atr_multiplier')} | "
                                f"{' ; '.join(adaptations_log)}"
                            )

                        return params
            # Адаптация по балансу (главный фактор)
            if balance is not None:
                (
                    balance_factor_tp,
                    balance_factor_sl,
                ) = self._calculate_balance_adaptation_factors(balance)
                adaptive_params["tp_atr_multiplier"] = tp_base * balance_factor_tp
                adaptive_params["sl_atr_multiplier"] = sl_base * balance_factor_sl

                logger.debug(
                    f"💰 [ADAPTIVE] {symbol}: Баланс ${balance:.0f} → "
                    f"TP: {tp_base:.2f} × {balance_factor_tp:.3f} = {adaptive_params['tp_atr_multiplier']:.2f}, "
                    f"SL: {sl_base:.2f} × {balance_factor_sl:.3f} = {adaptive_params['sl_atr_multiplier']:.2f}"
                )

            # Адаптация по P&L позиции
            if current_pnl is not None:
                pnl_factor = self._calculate_pnl_adaptation_factor(current_pnl)
                if pnl_factor != 1.0:
                    adaptive_params["tp_atr_multiplier"] *= pnl_factor
                    logger.debug(
                        f"📈 [ADAPTIVE] {symbol}: P&L {current_pnl:.1f}% → "
                        f"TP расширение ×{pnl_factor:.3f} = {adaptive_params['tp_atr_multiplier']:.2f}"
                    )

            # Адаптация по просадке
            if drawdown is not None:
                drawdown_factor = self._calculate_drawdown_adaptation_factor(drawdown)
                if drawdown_factor != 1.0:
                    adaptive_params["sl_atr_multiplier"] *= drawdown_factor
                    logger.debug(
                        f"📉 [ADAPTIVE] {symbol}: Просадка {drawdown:.1f}% → "
                        f"SL ужесточение ×{drawdown_factor:.3f} = {adaptive_params['sl_atr_multiplier']:.2f}"
                    )

            # Ограничения на финальные значения
            adaptive_params["tp_atr_multiplier"] = min(
                max(adaptive_params["tp_atr_multiplier"], 1.0), 5.0
            )
            adaptive_params["sl_atr_multiplier"] = min(
                max(adaptive_params["sl_atr_multiplier"], 0.5), 3.0
            )

            # Логирование итоговых адаптивных параметров
            # ✅ ИСПРАВЛЕНИЕ (07.01.2026): Добавлена защита от NoneType при форматировании
            balance_str = f"${balance:.0f}" if balance is not None else "N/A"
            pnl_str = f"{current_pnl:.1f}%" if current_pnl is not None else "N/A"
            drawdown_str = f"{drawdown:.1f}%" if drawdown is not None else "N/A"
            logger.info(
                f"🎯 [ADAPTIVE] {symbol} ({regime}): Финальные параметры → "
                f"TP: {adaptive_params['tp_atr_multiplier']:.2f}, "
                f"SL: {adaptive_params['sl_atr_multiplier']:.2f} | "
                f"Контекст: баланс={balance_str}, P&L={pnl_str}, просадка={drawdown_str}"
            )

            return adaptive_params

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка применения адаптивных параметров для {symbol}: {e}"
            )
            return base_params

    def get_smart_close_params(
        self, regime: str, symbol: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Получить адаптивные параметры Smart Close для режима.

        Приоритет:
        1. by_symbol.{symbol}.smart_close.{regime}
        2. exit_params.smart_close.{regime}
        3. Default значения

        Args:
            regime: Режим рынка (trending, ranging, choppy)
            symbol: Торговый символ (опционально, для per-symbol параметров)

        Returns:
            {
                'reversal_score_threshold': float,
                'trend_against_threshold': float
            }
        """
        defaults = {"reversal_score_threshold": 2.0, "trend_against_threshold": 0.7}

        try:
            # ✅ ПРИОРИТЕТ 1: by_symbol.{symbol}.smart_close.{regime}
            if symbol and hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                by_symbol = config_dict.get("by_symbol", {})
                symbol_config = by_symbol.get(symbol, {})
                if isinstance(symbol_config, dict):
                    smart_close_config = symbol_config.get("smart_close", {})
                    if isinstance(smart_close_config, dict):
                        regime_config = smart_close_config.get(regime, {})
                        if isinstance(regime_config, dict):
                            reversal_threshold = regime_config.get(
                                "reversal_score_threshold"
                            )
                            trend_threshold = regime_config.get(
                                "trend_against_threshold"
                            )
                            if (
                                reversal_threshold is not None
                                or trend_threshold is not None
                            ):
                                params = defaults.copy()
                                if reversal_threshold is not None:
                                    params["reversal_score_threshold"] = float(
                                        reversal_threshold
                                    )
                                if trend_threshold is not None:
                                    params["trend_against_threshold"] = float(
                                        trend_threshold
                                    )
                                logger.debug(
                                    f"✅ ParameterProvider: Smart Close параметры для {symbol} ({regime}) "
                                    f"получены из by_symbol: reversal={params['reversal_score_threshold']}, "
                                    f"trend={params['trend_against_threshold']}"
                                )
                                return params

            # ✅ ПРИОРИТЕТ 2: exit_params.smart_close.{regime}
            if hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                exit_params = config_dict.get("exit_params", {})
                if isinstance(exit_params, dict):
                    smart_close_config = exit_params.get("smart_close", {})
                    if isinstance(smart_close_config, dict):
                        regime_config = smart_close_config.get(regime, {})
                        if isinstance(regime_config, dict):
                            reversal_threshold = regime_config.get(
                                "reversal_score_threshold"
                            )
                            trend_threshold = regime_config.get(
                                "trend_against_threshold"
                            )
                            if (
                                reversal_threshold is not None
                                or trend_threshold is not None
                            ):
                                params = defaults.copy()
                                if reversal_threshold is not None:
                                    params["reversal_score_threshold"] = float(
                                        reversal_threshold
                                    )
                                if trend_threshold is not None:
                                    params["trend_against_threshold"] = float(
                                        trend_threshold
                                    )
                                logger.debug(
                                    f"✅ ParameterProvider: Smart Close параметры для {regime} "
                                    f"получены из exit_params: reversal={params['reversal_score_threshold']}, "
                                    f"trend={params['trend_against_threshold']}"
                                )
                                return params
        except Exception as e:
            logger.debug(
                f"⚠️ ParameterProvider: Ошибка получения Smart Close параметров для {symbol or 'default'} ({regime}): {e}"
            )

        # По умолчанию возвращаем стандартные значения
        logger.debug(
            f"✅ ParameterProvider: Smart Close параметры для {regime} - используются default: "
            f"reversal={defaults['reversal_score_threshold']}, trend={defaults['trend_against_threshold']}"
        )
        return defaults

    def get_symbol_params(self, symbol: str) -> Dict[str, Any]:
        """
        Получить параметры для конкретного символа.

        Args:
            symbol: Торговый символ

        Returns:
            Словарь с параметрами символа из symbol_profiles
        """
        try:
            return self.config_manager.get_symbol_profile(symbol) or {}
        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения параметров символа {symbol}: {e}"
            )
            return {}

                        )

            return indicators

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения параметров индикаторов для {symbol}: {e}"
            )
            return {}

    def get_rsi_thresholds(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Получить пороги RSI для режима и символа.

        Args:
            symbol: Торговый символ
            regime: Режим рынка. Если None, определяется автоматически

        Returns:
            {
                'overbought': float,
                'oversold': float,
                'period': int
            }
        """
        try:
            indicator_params = self.get_indicator_params(symbol, regime)
            return {
                "overbought": indicator_params.get("rsi_overbought", 70),
                "oversold": indicator_params.get("rsi_oversold", 30),
                "period": indicator_params.get("rsi_period", 14),
            }
        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения RSI порогов для {symbol}: {e}"
            )
            return {"overbought": 70, "oversold": 30, "period": 14}

    def get_module_params(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получить параметры модулей (фильтров) для режима.

        Args:
            symbol: Торговый символ
            regime: Режим рынка. Если None, определяется автоматически

        Returns:
            Словарь с параметрами модулей:
            {
                "mtf_block_opposite": bool,
                "mtf_score_bonus": int,
                "correlation_threshold": float,
                "max_correlated_positions": int,
                ...
            }
        """
        try:
            # Определяем режим если не указан
            if not regime:
                regime = self._get_current_regime(symbol)

            # Получаем параметры режима
            regime_params = self.get_regime_params(symbol, regime)

            # Извлекаем параметры модулей
            modules = regime_params.get("modules", {})
            if isinstance(modules, dict):
                return modules
            elif hasattr(modules, "__dict__"):
                return modules.__dict__
            else:
                return {}

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения параметров модулей для {symbol}: {e}"
            )
            return {}

    def get_risk_params(
        self, symbol: str, balance: float, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получить параметры управления рисками.

        Args:
            symbol: Торговый символ
            balance: Текущий баланс
            regime: Режим рынка. Если None, определяется автоматически

        Returns:
            Словарь с параметрами риска:
            {
                "max_margin_per_trade": float,
                "max_daily_loss_percent": float,
                "max_drawdown_percent": float,
                "min_balance_usd": float,
                ...
            }
        """
        try:
            # Определяем режим если не указан
            if not regime:
                regime = self._get_current_regime(symbol)

            # Получаем адаптивные параметры риска
            risk_params = self.config_manager.get_adaptive_risk_params(balance, regime)

            return risk_params

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения параметров риска для {symbol}: {e}"
            )
            return {}

    def get_trailing_sl_params(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получить параметры Trailing Stop Loss.

        Args:
            symbol: Торговый символ
            regime: Режим рынка. Если None, определяется автоматически

        Returns:
            Словарь с параметрами TSL
        """
        try:
            # Определяем режим если не указан
            if not regime:
                regime = self._get_current_regime(symbol)

            return self.config_manager.get_trailing_sl_params(regime=regime) or {}
        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения TSL параметров для {symbol}: {e}"
            )
            return {}

    def _get_current_regime(self, symbol: str) -> str:
        """
        Получить текущий режим рынка для символа.

        ✅ ИСПРАВЛЕНИЕ #22 (04.01.2026): Логируем fallback режим "ranging"
        """
        """
        Получить текущий режим рынка для символа.

        Args:
            symbol: Торговый символ

        Returns:
            Режим рынка (trending/ranging/choppy) или "ranging" по умолчанию
        """
        try:
            # Пробуем получить из DataRegistry (синхронный метод)
            if self.data_registry:
                regime = self.data_registry.get_regime_name_sync(symbol)
                if regime:
                    return regime.lower()

            # Пробуем получить из RegimeManager
            if self.regime_manager:
                regime = self.regime_manager.get_current_regime()
                if regime:
                    return (
                        regime.lower()
                        if isinstance(regime, str)
                        else str(regime).lower()
                    )

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка определения режима для {symbol}: {e}"
            )

        # ✅ ИСПРАВЛЕНИЕ #22 (04.01.2026): Логируем fallback режим "ranging"
        logger.warning(
            f"⚠️ ParameterProvider: Режим не определен для {symbol}, используется fallback 'ranging'"
        )
        return "ranging"

    def _get_default_regime_params(self) -> Dict[str, Any]:
        """
        Получить дефолтные параметры режима.

        Returns:
            Словарь с дефолтными параметрами
        """
        return {
            "min_score_threshold": 2.0,
            "max_trades_per_hour": 10,
            "position_size_multiplier": 1.0,
            "tp_atr_multiplier": 2.0,
            "sl_atr_multiplier": 1.5,
            "max_holding_minutes": 15,
            "cooldown_after_loss_minutes": 5,
        }

    def clear_cache(self, key: Optional[str] = None) -> None:
        """
        Очистить кэш параметров.

        Args:
            key: Ключ для очистки (если None - очистить весь кэш)
        """
        import time

        if key:
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
            logger.debug("✅ ParameterProvider: Кэш очищен")

    def get_cached_value(self, key: str) -> Optional[Any]:
        """
        Получить значение из кэша.

        Args:
            key: Ключ кэша

        Returns:
            Значение из кэша или None
        """
        import time

        if key not in self._cache:
            return None

        cache_time = self._cache_timestamps.get(key, 0)
        current_time = time.time()

        if current_time - cache_time > self._cache_ttl_seconds:
            # Кэш устарел
            return None

        return self._cache[key]

    def set_cached_value(self, key: str, value: Any) -> None:
        """
        Сохранить значение в кэш.

        Args:
            key: Ключ кэша
            value: Значение для кэширования
        """
        import time

        self._cache[key] = value
        self._cache_timestamps[key] = time.time()

    def _adapt_by_balance(
        self, balance: float, exit_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        ✅ НОВОЕ (05.01.2026): Адаптация TP/SL по балансу.

        Args:
            balance: Текущий баланс
            exit_params: Базовые параметры выхода

        Returns:
            Словарь с адаптированными параметрами (если применена адаптация)
        """
        # Получаем конфигурацию адаптации
        adaptive_config = self._get_adaptive_exit_config()

        if not adaptive_config.get("enabled", False):
            return {}

        balance_config = adaptive_config.get("balance_adaptation", {})
        if not balance_config:
            return {}

        # Определяем профиль баланса
        if balance < 1500:
            profile = "small"
        elif balance < 3500:
            profile = "medium"
        else:
            profile = "large"

        profile_config = balance_config.get(profile, {})
        if not profile_config:
            return {}

        # Применяем множители
        tp_multiplier = profile_config.get("tp_multiplier", 1.0)
        sl_multiplier = profile_config.get("sl_multiplier", 1.0)

        base_tp = exit_params.get("tp_atr_multiplier", 2.0)
        base_sl = exit_params.get("sl_atr_multiplier", 1.5)

        adapted = {}
        if tp_multiplier != 1.0:
            adapted["tp_atr_multiplier"] = base_tp * tp_multiplier
        if sl_multiplier != 1.0:
            adapted["sl_atr_multiplier"] = base_sl * sl_multiplier

        return adapted

    def _adapt_tp_by_pnl(
        self, current_pnl: float, exit_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        ✅ НОВОЕ (05.01.2026): Расширение TP при сильном P&L.

        Args:
            current_pnl: Текущий P&L позиции в %
            exit_params: Базовые параметры выхода

        Returns:
            Словарь с адаптированным TP (если применена адаптация)
        """
        # Получаем конфигурацию адаптации
        adaptive_config = self._get_adaptive_exit_config()

        if not adaptive_config.get("enabled", False):
            return {}

        pnl_config = adaptive_config.get("pnl_adaptation", {})
        if not pnl_config.get("enabled", False):
            return {}

        base_tp = exit_params.get("tp_atr_multiplier", 2.0)
        extension_threshold = pnl_config.get(
            "extension_threshold", 0.8
        )  # 80% от базового TP
        max_extension = pnl_config.get("max_extension", 0.5)  # Макс +0.5x
        extension_factor = pnl_config.get("extension_factor", 0.3)  # Коэффициент

        # Если P&L уже превысил порог расширения
        threshold_pnl = base_tp * extension_threshold
        if current_pnl > threshold_pnl:
            # Рассчитываем расширение
            excess_pnl = current_pnl - threshold_pnl
            extension = min(excess_pnl * extension_factor, max_extension)
            new_tp = base_tp + extension

            return {"tp_atr_multiplier": new_tp}

        return {}

    def _adapt_sl_by_drawdown(
        self, drawdown: float, exit_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        ✅ НОВОЕ (05.01.2026): Ужесточение SL при просадке.

        Фаза 2 - будет реализовано позже.

        Args:
            drawdown: Текущая просадка в %
            exit_params: Базовые параметры выхода

        Returns:
            Словарь с адаптированным SL (если применена адаптация)
        """
        # Получаем конфигурацию адаптации
        adaptive_config = self._get_adaptive_exit_config()

        if not adaptive_config.get("enabled", False):
            return {}

        drawdown_config = adaptive_config.get("drawdown_adaptation", {})
        if not drawdown_config.get("enabled", False):
            return {}

        base_sl = exit_params.get("sl_atr_multiplier", 1.5)
        tightening_threshold = drawdown_config.get("tightening_threshold", 5.0)  # 5%
        max_tightening = drawdown_config.get("max_tightening", 0.3)  # Макс +0.3x
        tightening_factor = drawdown_config.get("tightening_factor", 0.1)  # Коэффициент

        # Если просадка > порога, ужесточаем SL
        if drawdown > tightening_threshold:
            excess_drawdown = drawdown - tightening_threshold
            tightening = min(excess_drawdown * tightening_factor, max_tightening)
            new_sl = base_sl + tightening

            return {"sl_atr_multiplier": new_sl}

        return {}

    def _apply_adaptive_exit_params(
        self,
        base_params: Dict[str, Any],
        symbol: str,
        regime: Optional[str],
        balance: Optional[float],
        current_pnl: Optional[float],
        drawdown: Optional[float],
    ) -> Dict[str, Any]:
        """
        ✅ НОВОЕ (06.01.2026): Применить адаптивную логику к параметрам выхода.

        Использует плавную интерполяцию по балансу для расчета TP/SL множителей.

        Args:
            base_params: Базовые параметры выхода
            symbol: Торговый символ
            regime: Режим рынка
            balance: Текущий баланс
            current_pnl: Текущий P&L позиции в %
            drawdown: Текущая просадка в %

        Returns:
            Адаптивные параметры выхода
        """
        try:
            # Проверяем, включена ли адаптация
            adaptive_config = self._get_adaptive_exit_config()
            if not adaptive_config.get("enabled", False):
                logger.debug("⚠️ Адаптивные параметры отключены в конфигурации")
                return base_params

            # Копируем базовые параметры
            adaptive_params = base_params.copy()

            # Получаем базовые множители
            tp_base = base_params.get("tp_atr_multiplier", 2.0)
            sl_base = base_params.get("sl_atr_multiplier", 1.5)

            # Адаптация по балансу (главный фактор)
            if balance is not None:
                (
                    balance_factor_tp,
                    balance_factor_sl,
                ) = self._calculate_balance_adaptation_factors(balance)
                adaptive_params["tp_atr_multiplier"] = tp_base * balance_factor_tp
                adaptive_params["sl_atr_multiplier"] = sl_base * balance_factor_sl

                logger.debug(
                    f"💰 [ADAPTIVE] {symbol}: Баланс ${balance:.0f} → "
                    f"TP: {tp_base:.2f} × {balance_factor_tp:.3f} = {adaptive_params['tp_atr_multiplier']:.2f}, "
                    f"SL: {sl_base:.2f} × {balance_factor_sl:.3f} = {adaptive_params['sl_atr_multiplier']:.2f}"
                )

            # Адаптация по P&L позиции
            if current_pnl is not None:
                pnl_factor = self._calculate_pnl_adaptation_factor(current_pnl)
                if pnl_factor != 1.0:
                    adaptive_params["tp_atr_multiplier"] *= pnl_factor
                    logger.debug(
                        f"📈 [ADAPTIVE] {symbol}: P&L {current_pnl:.1f}% → "
                        f"TP расширение ×{pnl_factor:.3f} = {adaptive_params['tp_atr_multiplier']:.2f}"
                    )

            # Адаптация по просадке
            if drawdown is not None:
                drawdown_factor = self._calculate_drawdown_adaptation_factor(drawdown)
                if drawdown_factor != 1.0:
                    adaptive_params["sl_atr_multiplier"] *= drawdown_factor
                    logger.debug(
                        f"📉 [ADAPTIVE] {symbol}: Просадка {drawdown:.1f}% → "
                        f"SL ужесточение ×{drawdown_factor:.3f} = {adaptive_params['sl_atr_multiplier']:.2f}"
                    )

            # Ограничения на финальные значения
            adaptive_params["tp_atr_multiplier"] = min(
                max(adaptive_params["tp_atr_multiplier"], 1.0), 5.0
            )
            adaptive_params["sl_atr_multiplier"] = min(
                max(adaptive_params["sl_atr_multiplier"], 0.5), 3.0
            )

            # Логирование итоговых адаптивных параметров
            # ✅ ИСПРАВЛЕНИЕ (07.01.2026): Добавлена защита от NoneType при форматировании
            balance_str = f"${balance:.0f}" if balance is not None else "N/A"
            pnl_str = f"{current_pnl:.1f}%" if current_pnl is not None else "N/A"
            drawdown_str = f"{drawdown:.1f}%" if drawdown is not None else "N/A"
            logger.info(
                f"🎯 [ADAPTIVE] {symbol} ({regime}): Финальные параметры → "
                f"TP: {adaptive_params['tp_atr_multiplier']:.2f}, "
                f"SL: {adaptive_params['sl_atr_multiplier']:.2f} | "
                f"Контекст: баланс={balance_str}, P&L={pnl_str}, просадка={drawdown_str}"
            )

            return adaptive_params

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка применения адаптивных параметров для {symbol}: {e}"
            )
            return base_params

    def _calculate_balance_adaptation_factors(
        self, balance: float
    ) -> tuple[float, float]:
        """
        Рассчитать коэффициенты адаптации по балансу (плавная интерполяция).

        Использует линейную интерполяцию между порогами для плавного перехода.

        Returns:
            (tp_factor, sl_factor)
        """
        # Пороги из тестирования
        SMALL_THRESHOLD = 1500  # < $1500 - консервативный
        LARGE_THRESHOLD = 3500  # >= $3500 - агрессивный

        # Коэффициенты для каждого диапазона
        SMALL_TP = 0.9  # Консервативный TP для низких балансов
        SMALL_SL = 0.9  # Ужесточенный SL для низких балансов
        MEDIUM_TP = 1.0  # Стандартный TP
        MEDIUM_SL = 1.0  # Стандартный SL
        LARGE_TP = 1.1  # Агрессивный TP для высоких балансов
        LARGE_SL = 1.0  # Стандартный SL для высоких балансов

        if balance < SMALL_THRESHOLD:
            # От $500 до SMALL_THRESHOLD: интерполяция от консервативного к стандартному
            if balance <= 500:
                # Очень низкий баланс - максимально консервативный
                tp_factor = 0.8
                sl_factor = 0.8
            else:
                # Линейная интерполяция от 0.8 до 0.9
                ratio = (balance - 500) / (SMALL_THRESHOLD - 500)
                tp_factor = 0.8 + (SMALL_TP - 0.8) * ratio
                sl_factor = 0.8 + (SMALL_SL - 0.8) * ratio

        elif balance < LARGE_THRESHOLD:
            # От SMALL_THRESHOLD до LARGE_THRESHOLD: интерполяция от 0.9 до 1.0
            ratio = (balance - SMALL_THRESHOLD) / (LARGE_THRESHOLD - SMALL_THRESHOLD)
            tp_factor = SMALL_TP + (MEDIUM_TP - SMALL_TP) * ratio
            sl_factor = SMALL_SL + (MEDIUM_SL - SMALL_SL) * ratio

        else:
            # От LARGE_THRESHOLD и выше: интерполяция от 1.0 до 1.1 (до баланса $5000)
            if balance >= 5000:
                tp_factor = LARGE_TP
                sl_factor = LARGE_SL
            else:
                ratio = (balance - LARGE_THRESHOLD) / (5000 - LARGE_THRESHOLD)
                tp_factor = MEDIUM_TP + (LARGE_TP - MEDIUM_TP) * ratio
                sl_factor = MEDIUM_SL + (LARGE_SL - MEDIUM_SL) * ratio

        return tp_factor, sl_factor

    def _calculate_pnl_adaptation_factor(self, current_pnl: float) -> float:
        """
        Рассчитать коэффициент адаптации по P&L позиции.

        При положительном P&L расширяет TP для захвата прибыли.
        """
        # Расширение TP при сильном профите
        if current_pnl > 5.0:  # > 5%
            extension = min((current_pnl - 5.0) * 0.3, 0.5)  # Макс +0.5x
            return 1.0 + extension
        return 1.0

    def _calculate_drawdown_adaptation_factor(self, drawdown: float) -> float:
        """
        Рассчитать коэффициент адаптации по просадке.

        При высокой просадке ужесточает SL для защиты капитала.
        """
        # Ужесточение SL при просадке
        if drawdown > 5.0:  # > 5%
            tightening = min((drawdown - 5.0) * 0.1, 0.3)  # Макс +0.3x
            return 1.0 + tightening
        return 1.0

    def _get_adaptive_exit_config(self) -> Dict[str, Any]:
        """
        ✅ НОВОЕ (05.01.2026): Получить конфигурацию адаптивных параметров выхода.

        Returns:
            Словарь с конфигурацией адаптации
        """
        try:
            if hasattr(self.config_manager, "_raw_config_dict"):
                config_dict = self.config_manager._raw_config_dict
                return config_dict.get("adaptive_exit_params", {})
        except Exception as e:
            logger.debug(
                f"⚠️ ParameterProvider: Ошибка получения adaptive_exit_params: {e}"
            )

        # Возвращаем дефолтную конфигурацию
        return {
            "enabled": False,  # По умолчанию выключено
            "balance_adaptation": {
                "small": {"tp_multiplier": 0.9, "sl_multiplier": 0.9},
                "medium": {"tp_multiplier": 1.0, "sl_multiplier": 1.0},
                "large": {"tp_multiplier": 1.1, "sl_multiplier": 1.0},
            },
            "pnl_adaptation": {
                "enabled": True,
                "extension_threshold": 0.8,
                "max_extension": 0.5,
                "extension_factor": 0.3,
            },
            "drawdown_adaptation": {
                "enabled": False,  # Фаза 2
                "tightening_threshold": 5.0,
                "max_tightening": 0.3,
                "tightening_factor": 0.1,
            },
        }
