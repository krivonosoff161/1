"""
RegimeCalculator - Расчеты TP/SL для режимов.

Рассчитывает TP/SL проценты с учетом:
- Per-regime параметры
- Per-symbol переопределения
- Balance profile boost
"""

from typing import Any, Dict, Optional

from loguru import logger


class RegimeCalculator:
    """
    Калькулятор параметров режима.

    Рассчитывает TP/SL проценты для режимов с учетом всех приоритетов.
    """

    def __init__(self, config=None):
        """
        Инициализация RegimeCalculator.

        Args:
            config: Конфигурация бота (для доступа к symbol_profiles и т.д.)
        """
        self.config = config
        self.symbol_profiles = None

        if config and hasattr(config, "scalping"):
            scalping_config = config.scalping
            if hasattr(scalping_config, "symbol_profiles"):
                self.symbol_profiles = scalping_config.symbol_profiles

        logger.info("✅ RegimeCalculator инициализирован")

    def calculate_tp_percent(
        self,
        symbol: str,
        regime: Optional[str] = None,
        balance_profile: Optional[str] = None,
    ) -> float:
        """
        Рассчитать TP процент для символа и режима.

        Приоритет:
        1. Per-regime TP (если режим определен)
        2. Per-symbol TP
        3. Глобальный TP
        4. Balance profile boost (применяется ко всем)

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            balance_profile: Профиль баланса (small, medium, large) - для boost

        Returns:
            TP процент
        """
        tp_percent = None

        # Получаем TP из конфига
        if self.symbol_profiles and symbol in self.symbol_profiles:
            symbol_profile = self.symbol_profiles.get(symbol, {})

            # Преобразуем в dict если нужно
            if not isinstance(symbol_profile, dict):
                if hasattr(symbol_profile, "dict"):
                    symbol_dict = symbol_profile.dict()
                elif hasattr(symbol_profile, "__dict__"):
                    symbol_dict = dict(symbol_profile.__dict__)
                else:
                    symbol_dict = {}
            else:
                symbol_dict = symbol_profile

            # 1. Per-regime TP
            if regime:
                regime_lower = regime.lower()
                regime_profile = symbol_dict.get(regime_lower, {})
                if not isinstance(regime_profile, dict):
                    regime_profile = self._to_dict(regime_profile)

                regime_tp = regime_profile.get("tp_percent")
                if regime_tp is not None:
                    try:
                        tp_percent = float(regime_tp)
                        logger.debug(
                            f"✅ RegimeCalculator: Per-regime TP для {symbol} ({regime}): {tp_percent}%"
                        )
                    except (ValueError, TypeError):
                        pass

            # 2. Per-symbol TP (fallback)
            if tp_percent is None:
                symbol_tp = symbol_dict.get("tp_percent")
                if symbol_tp is not None:
                    try:
                        tp_percent = float(symbol_tp)
                        logger.debug(
                            f"✅ RegimeCalculator: Per-symbol TP для {symbol}: {tp_percent}%"
                        )
                    except (ValueError, TypeError):
                        pass

        # 3. Глобальный TP (fallback)
        if tp_percent is None:
            if self.config and hasattr(self.config, "scalping"):
                tp_percent = getattr(self.config.scalping, "tp_percent", 0.5)
            else:
                tp_percent = 0.5  # Default

            logger.debug(
                f"ℹ️ RegimeCalculator: Глобальный TP для {symbol}: {tp_percent}%"
            )

        # 4. Balance profile boost
        if balance_profile:
            boost = self._get_balance_profile_boost(balance_profile, "tp")
            if boost != 1.0:
                tp_percent = tp_percent * boost
                logger.debug(
                    f"📊 RegimeCalculator: Balance boost для {symbol} ({balance_profile}): TP={tp_percent:.2f}%"
                )

        return tp_percent

    def calculate_sl_percent(
        self,
        symbol: str,
        regime: Optional[str] = None,
        balance_profile: Optional[str] = None,
    ) -> float:
        """
        Рассчитать SL процент для символа и режима.

        Приоритет:
        1. Per-regime SL (если режим определен)
        2. Per-symbol SL
        3. Глобальный SL
        4. Balance profile boost (применяется ко всем)

        Args:
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            balance_profile: Профиль баланса (small, medium, large) - для boost

        Returns:
            SL процент
        """
        sl_percent = None

        # Получаем SL из конфига
        if self.symbol_profiles and symbol in self.symbol_profiles:
            symbol_profile = self.symbol_profiles.get(symbol, {})

            # Преобразуем в dict если нужно
            if not isinstance(symbol_profile, dict):
                symbol_dict = self._to_dict(symbol_profile)
            else:
                symbol_dict = symbol_profile

            # 1. Per-regime SL
            if regime:
                regime_lower = regime.lower()
                regime_profile = symbol_dict.get(regime_lower, {})
                if not isinstance(regime_profile, dict):
                    regime_profile = self._to_dict(regime_profile)

                regime_sl = regime_profile.get("sl_percent")
                if regime_sl is not None:
                    try:
                        sl_percent = float(regime_sl)
                        logger.debug(
                            f"✅ RegimeCalculator: Per-regime SL для {symbol} ({regime}): {sl_percent}%"
                        )
                    except (ValueError, TypeError):
                        pass

            # 2. Per-symbol SL (fallback)
            if sl_percent is None:
                symbol_sl = symbol_dict.get("sl_percent")
                if symbol_sl is not None:
                    try:
                        sl_percent = float(symbol_sl)
                        logger.debug(
                            f"✅ RegimeCalculator: Per-symbol SL для {symbol}: {sl_percent}%"
                        )
                    except (ValueError, TypeError):
                        pass

        # 3. Глобальный SL (fallback)
        if sl_percent is None:
            if self.config and hasattr(self.config, "scalping"):
                sl_percent = getattr(self.config.scalping, "sl_percent", 0.3)
            else:
                sl_percent = 0.3  # Default

            logger.debug(
                f"ℹ️ RegimeCalculator: Глобальный SL для {symbol}: {sl_percent}%"
            )

        # 4. Balance profile boost (для SL обычно не применяется или применяется обратно)
        # TODO: Определить, нужен ли boost для SL

        return sl_percent

    def calculate_position_size_multiplier(
        self,
        symbol: str,
        regime: Optional[str] = None,
        balance_profile: Optional[str] = None,
    ) -> float:
        """
        Рассчитать множитель размера позиции.

        Args:
            symbol: Торговый символ
            regime: Режим рынка
            balance_profile: Профиль баланса

        Returns:
            Множитель размера позиции
        """
        multiplier = 1.0

        # Получаем multiplier из конфига
        if self.symbol_profiles and symbol in self.symbol_profiles:
            symbol_profile = self.symbol_profiles.get(symbol, {})
            symbol_dict = self._to_dict(symbol_profile) if not isinstance(symbol_profile, dict) else symbol_profile

            # Per-regime multiplier
            if regime:
                regime_lower = regime.lower()
                regime_profile = symbol_dict.get(regime_lower, {})
                if not isinstance(regime_profile, dict):
                    regime_profile = self._to_dict(regime_profile)

                regime_mult = regime_profile.get("position_multiplier")
                if regime_mult is not None:
                    try:
                        multiplier = float(regime_mult)
                    except (ValueError, TypeError):
                        pass

            # Per-symbol multiplier (fallback)
            if multiplier == 1.0:
                symbol_mult = symbol_dict.get("position_multiplier")
                if symbol_mult is not None:
                    try:
                        multiplier = float(symbol_mult)
                    except (ValueError, TypeError):
                        pass

        # Balance profile boost
        if balance_profile:
            boost = self._get_balance_profile_boost(balance_profile, "position_size")
            multiplier = multiplier * boost

        return multiplier

    def _get_balance_profile_boost(
        self, balance_profile: str, param_type: str
    ) -> float:
        """
        Получить boost множитель для профиля баланса.

        Args:
            balance_profile: Профиль баланса (small, medium, large)
            param_type: Тип параметра (tp, sl, position_size)

        Returns:
            Boost множитель
        """
        # TODO: Реализовать логику boost из конфига
        # Пока возвращаем 1.0 (без boost)
        return 1.0

    def _to_dict(self, obj: Any) -> Dict[str, Any]:
        """Преобразовать объект в словарь"""
        if isinstance(obj, dict):
            return obj
        elif hasattr(obj, "dict"):
            return obj.dict()
        elif hasattr(obj, "__dict__"):
            return dict(obj.__dict__)
        else:
            return {}

