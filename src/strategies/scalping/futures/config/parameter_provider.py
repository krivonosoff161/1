"""
Parameter Provider - Единая точка получения параметров торговли.

Обеспечивает централизованный доступ к параметрам из различных источников:
- ConfigManager
- RegimeManager
- Symbol profiles
- Adaptive risk parameters

Предотвращает дублирование кода и обеспечивает консистентность параметров.
"""

from typing import Any, Dict, Optional

from loguru import logger

from .config_manager import ConfigManager


class ParameterProvider:
    """
    Единая точка получения параметров торговли.

    Объединяет доступ к параметрам из различных источников и предоставляет
    единый интерфейс для всех модулей системы.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        regime_manager=None,  # AdaptiveRegimeManager (опционально)
        data_registry=None,  # DataRegistry (опционально)
    ):
        """
        Инициализация Parameter Provider.

        Args:
            config_manager: ConfigManager для доступа к конфигурации
            regime_manager: AdaptiveRegimeManager для режим-специфичных параметров (опционально)
            data_registry: DataRegistry для текущих режимов (опционально)
        """
        self.config_manager = config_manager
        self.regime_manager = regime_manager
        self.data_registry = data_registry

        # Кэш для часто используемых параметров
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_ttl_seconds = 300.0  # ✅ ИСПРАВЛЕНО (28.12.2025): Увеличено с 60 до 300 секунд (5 минут) для снижения нагрузки

        logger.info("✅ ParameterProvider инициализирован")

    def get_regime_params(
        self,
        symbol: str,
        regime: Optional[str] = None,
        balance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Получить параметры для режима рынка.

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending/ranging/choppy). Если None, определяется автоматически
            balance: Текущий баланс (для адаптивных параметров)

        Returns:
            Словарь с параметрами режима:
            {
                "min_score_threshold": float,
                "max_trades_per_hour": int,
                "position_size_multiplier": float,
                "tp_atr_multiplier": float,
                "sl_atr_multiplier": float,
                "max_holding_minutes": int,
                "cooldown_after_loss_minutes": int,
                ...
            }
        """
        try:
            # Определяем режим если не указан
            if not regime:
                regime = self._get_current_regime(symbol)

            # Получаем параметры из ConfigManager
            regime_params = self.config_manager.get_regime_params(regime)

            # Применяем адаптивные параметры если баланс указан
            if balance is not None:
                adaptive_params = self.config_manager.get_adaptive_risk_params(
                    balance, regime
                )
                # Объединяем параметры (адаптивные имеют приоритет)
                regime_params = {**regime_params, **adaptive_params}

            return regime_params

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения параметров режима для {symbol}: {e}"
            )
            # Возвращаем дефолтные параметры
            return self._get_default_regime_params()

    def get_exit_params(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получить параметры выхода (TP/SL) для режима.

        Args:
            symbol: Торговый символ
            regime: Режим рынка. Если None, определяется автоматически

        Returns:
            Словарь с параметрами выхода:
            {
                "tp_atr_multiplier": float,
                "sl_atr_multiplier": float,
                "max_holding_minutes": int,
                "emergency_loss_threshold": float,
                ...
            }
        """
        try:
            # Определяем режим если не указан
            if not regime:
                regime = self._get_current_regime(symbol)

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Получаем exit_params напрямую из raw_config_dict
            # ConfigManager не имеет метода get_exit_param, получаем через _raw_config_dict
            exit_params = {}
            if (
                hasattr(self.config_manager, "_raw_config_dict")
                and self.config_manager._raw_config_dict
            ):
                all_exit_params = self.config_manager._raw_config_dict.get(
                    "exit_params", {}
                )
                if isinstance(all_exit_params, dict) and regime:
                    regime_lower = (
                        regime.lower()
                        if isinstance(regime, str)
                        else str(regime).lower()
                    )
                    exit_params = all_exit_params.get(regime_lower, {})
                elif isinstance(all_exit_params, dict):
                    # Если режим не указан, возвращаем все exit_params
                    exit_params = all_exit_params

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Конвертация типов для всех числовых параметров
            # Предотвращает TypeError при сравнении str и int/float
            def _to_float(value: Any, name: str, default: float = 0.0) -> float:
                """Helper для безопасной конвертации в float"""
                if value is None:
                    return default
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"⚠️ ParameterProvider: Не удалось конвертировать {name}={value} в float, "
                            f"используем default={default}"
                        )
                        return default
                return default

            # Конвертируем ключевые параметры
            if exit_params:
                exit_params["max_holding_minutes"] = _to_float(
                    exit_params.get("max_holding_minutes"),
                    "max_holding_minutes",
                    25.0
                    if regime and regime.lower() == "ranging"
                    else 120.0,  # Default для ranging: 25.0, иначе 120.0
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

            return exit_params or {}

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения exit_params для {symbol}: {e}"
            )
            return {}

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

    def get_indicator_params(
        self, symbol: str, regime: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получить параметры индикаторов для режима.

        Args:
            symbol: Торговый символ
            regime: Режим рынка. Если None, определяется автоматически

        Returns:
            Словарь с параметрами индикаторов:
            {
                "rsi_period": int,
                "rsi_overbought": float,
                "rsi_oversold": float,
                "atr_period": int,
                "sma_fast": int,
                "sma_slow": int,
                "ema_fast": int,
                "ema_slow": int,
                ...
            }
        """
        try:
            # Определяем режим если не указан
            if not regime:
                regime = self._get_current_regime(symbol)

            # Получаем параметры режима
            regime_params = self.get_regime_params(symbol, regime)

            # Извлекаем параметры индикаторов
            indicators = regime_params.get("indicators", {})
            if isinstance(indicators, dict):
                return indicators
            elif hasattr(indicators, "__dict__"):
                return indicators.__dict__
            else:
                return {}

        except Exception as e:
            logger.warning(
                f"⚠️ ParameterProvider: Ошибка получения параметров индикаторов для {symbol}: {e}"
            )
            return {}

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
            logger.debug(
                f"⚠️ ParameterProvider: Ошибка определения режима для {symbol}: {e}"
            )

        # Fallback на ranging
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
