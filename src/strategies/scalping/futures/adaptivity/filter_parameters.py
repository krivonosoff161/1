"""
Адаптивная система параметров фильтров V2.

Все параметры читаются из ConfigManager и адаптируются по:
- Режиму рынка (trending/ranging/choppy)
- Волатильности (ATR)
- Win Rate (производительность)

Использует взвешенное суммирование вместо мультипликативных цепочек.
"""

import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from ..config.config_manager import ConfigManager
from ..core.data_registry import DataRegistry
from .regime_manager import AdaptiveRegimeManager


class AdaptiveFilterParameters:
    """
    Централизованная адаптивная система параметров фильтров.

    Все параметры читаются из ConfigManager и адаптируются динамически.
    """

    # Веса факторов (глобальные)
    WEIGHTS = {
        "regime": 0.5,  # 50% влияния
        "volatility": 0.3,  # 30% влияния
        "winrate": 0.2,  # 20% влияния
    }

    def __init__(
        self,
        config_manager: ConfigManager,
        regime_manager: AdaptiveRegimeManager,
        data_registry: DataRegistry,
        trading_statistics=None,
    ):
        """
        Инициализация адаптивной системы фильтров.

        Args:
            config_manager: ConfigManager для чтения базовых значений
            regime_manager: AdaptiveRegimeManager для получения режима
            data_registry: DataRegistry для получения волатильности
            trading_statistics: TradingStatistics для получения win rate
        """
        self.config_manager = config_manager
        self.regime_manager = regime_manager
        self.data_registry = data_registry
        self.trading_statistics = trading_statistics

        # ✅ ИСПРАВЛЕНИЕ #23 (04.01.2026): Уменьшено TTL кэша с 60 до 15 секунд для более быстрого обновления
        self._cache: Dict[str, Tuple[float, float]] = {}  # {key: (value, timestamp)}
        self._cache_ttl = 15.0

        # Метрики для валидации
        self.metrics = {
            "parameter_changes": [],  # История изменений
            "regime_switches": [],  # История смен режимов
        }

        logger.info("✅ AdaptiveFilterParameters инициализирован")

    async def get_reversal_threshold(
        self, symbol: str, regime: Optional[str] = None
    ) -> float:
        """
        Адаптивный порог V-образного разворота.

        Args:
            symbol: Торговый символ
            regime: Режим рынка (если None - определяется автоматически)

        Returns:
            Адаптированный порог (0.05% - 0.5%)
        """
        cache_key = f"reversal_threshold_{symbol}_{regime}"

        # Проверяем кэш
        if cache_key in self._cache:
            value, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return value

        # ✅ Читаем базовое значение из ConfigManager
        base = self._get_base_value(
            "reversal_threshold", symbol, regime, fallback=0.0015
        )

        # Получаем факторы
        regime_factor = self._get_regime_factor("reversal_threshold", regime, symbol)
        vol_factor = await self._get_volatility_factor("reversal_threshold", symbol)
        winrate_factor = self._get_winrate_factor("reversal_threshold", symbol)

        # Взвешенное суммирование
        multiplier = 1.0 + (
            self.WEIGHTS["regime"] * regime_factor
            + self.WEIGHTS["volatility"] * vol_factor
            + self.WEIGHTS["winrate"] * winrate_factor
        )

        threshold = base * multiplier

        # Ограничения
        threshold = max(0.0005, min(0.005, threshold))

        # Кэшируем
        self._cache[cache_key] = (threshold, time.time())

        # Логируем значительные изменения (>10%)
        if abs((threshold - base) / base) > 0.1:
            logger.debug(
                f"📊 reversal_threshold для {symbol}: {base:.4f} → {threshold:.4f} "
                f"({((threshold - base) / base) * 100:+.1f}%) | "
                f"regime={regime_factor:.2f}, vol={vol_factor:.2f}, wr={winrate_factor:.2f}"
            )

        return threshold

    async def get_adx_threshold(
        self, symbol: str, regime: Optional[str] = None
    ) -> float:
        """Адаптивный ADX threshold"""
        cache_key = f"adx_threshold_{symbol}_{regime}"

        if cache_key in self._cache:
            value, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return value

        base = self._get_base_value("adx_threshold", symbol, regime, fallback=20.0)

        regime_factor = self._get_regime_factor("adx_threshold", regime, symbol)
        vol_factor = await self._get_volatility_factor("adx_threshold", symbol)
        winrate_factor = self._get_winrate_factor("adx_threshold", symbol)

        multiplier = 1.0 + (
            self.WEIGHTS["regime"] * regime_factor
            + self.WEIGHTS["volatility"] * vol_factor
            + self.WEIGHTS["winrate"] * winrate_factor
        )

        threshold = base * multiplier
        threshold = max(15.0, min(28.0, threshold))

        self._cache[cache_key] = (threshold, time.time())
        return threshold

    def get_correlation_threshold(
        self, symbol: str, regime: Optional[str] = None
    ) -> float:
        """Адаптивный correlation threshold"""
        cache_key = f"correlation_threshold_{symbol}_{regime}"

        if cache_key in self._cache:
            value, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return value

        base = self._get_base_value(
            "correlation_threshold", symbol, regime, fallback=0.7
        )

        regime_factor = self._get_regime_factor("correlation_threshold", regime, symbol)
        vol_factor = 0.0  # Волатильность не влияет на correlation
        winrate_factor = self._get_winrate_factor("correlation_threshold", symbol)

        multiplier = 1.0 + (
            self.WEIGHTS["regime"] * regime_factor
            + self.WEIGHTS["winrate"] * winrate_factor
        )

        threshold = base * multiplier
        threshold = max(0.5, min(0.8, threshold))

        self._cache[cache_key] = (threshold, time.time())
        return threshold

    def get_min_signal_strength(
        self, symbol: str, regime: Optional[str] = None
    ) -> float:
        """Адаптивный min signal strength"""
        cache_key = f"min_signal_strength_{symbol}_{regime}"

        if cache_key in self._cache:
            value, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return value

        # Читаем из конфига
        base = getattr(self.config_manager.scalping_config, "min_signal_strength", 0.7)

        # Для ranging режима используем более строгий порог
        if regime == "ranging" or (
            regime is None and self._get_current_regime(symbol) == "ranging"
        ):
            base = getattr(
                self.config_manager.scalping_config, "min_signal_strength_ranging", base
            )

        regime_factor = self._get_regime_factor("min_signal_strength", regime, symbol)
        vol_factor = 0.0  # Волатильность не влияет
        winrate_factor = self._get_winrate_factor("min_signal_strength", symbol)

        multiplier = 1.0 + (
            self.WEIGHTS["regime"] * regime_factor
            + self.WEIGHTS["winrate"] * winrate_factor
        )

        strength = base * multiplier
        strength = max(0.5, min(0.85, strength))

        self._cache[cache_key] = (strength, time.time())
        return strength

    async def get_macd_divisor(
        self, symbol: str, regime: Optional[str] = None
    ) -> float:
        """Адаптивный MACD strength divisor"""
        cache_key = f"macd_divisor_{symbol}_{regime}"

        if cache_key in self._cache:
            value, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return value

        base = 200.0

        regime_factor = self._get_regime_factor("macd_divisor", regime, symbol)
        vol_factor = await self._get_volatility_factor("macd_divisor", symbol)
        winrate_factor = 0.0  # Win rate не влияет

        multiplier = 1.0 + (
            self.WEIGHTS["regime"] * regime_factor
            + self.WEIGHTS["volatility"] * vol_factor
        )

        divisor = base * multiplier
        divisor = max(150.0, min(280.0, divisor))

        self._cache[cache_key] = (divisor, time.time())
        return divisor

    async def get_strength_multiplier(
        self, symbol: str, regime: Optional[str] = None
    ) -> float:
        """Адаптивный strength multiplier"""
        cache_key = f"strength_multiplier_{symbol}_{regime}"

        if cache_key in self._cache:
            value, timestamp = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return value

        base = 2000.0

        regime_factor = self._get_regime_factor("strength_multiplier", regime, symbol)
        vol_factor = await self._get_volatility_factor("strength_multiplier", symbol)

        multiplier = 1.0 + (
            self.WEIGHTS["regime"] * regime_factor
            + self.WEIGHTS["volatility"] * vol_factor
        )

        result = base * multiplier
        result = max(1500.0, min(2800.0, result))

        self._cache[cache_key] = (result, time.time())
        return result

    def _get_base_value(
        self, param_name: str, symbol: str, regime: Optional[str], fallback: float
    ) -> float:
        """
        Получить базовое значение параметра из ConfigManager.

        Приоритет:
        1. per-symbol per-regime (symbol_profiles)
        2. per-regime (adaptive_regime)
        3. global (scalping_config)
        4. fallback
        """
        try:
            # Пробуем получить из symbol_profiles
            if symbol and hasattr(self.config_manager, "symbol_profiles"):
                symbol_profiles = self.config_manager.symbol_profiles
                if symbol in symbol_profiles:
                    symbol_config = symbol_profiles[symbol]
                    if isinstance(symbol_config, dict):
                        # Пробуем per-regime
                        if regime and regime in symbol_config:
                            regime_config = symbol_config[regime]
                            if isinstance(regime_config, dict):
                                # Ищем в reversal_detection для reversal_threshold
                                if param_name == "reversal_threshold":
                                    reversal_config = regime_config.get(
                                        "reversal_detection", {}
                                    )
                                    if isinstance(reversal_config, dict):
                                        v_reversal = reversal_config.get(
                                            "v_reversal_threshold"
                                        )
                                        if v_reversal is not None:
                                            return (
                                                float(v_reversal) / 100.0
                                            )  # Конвертируем из процентов

                                # Для других параметров ищем напрямую
                                value = regime_config.get(param_name)
                                if value is not None:
                                    return float(value)

                        # Пробуем глобальный для символа
                        value = symbol_config.get(param_name)
                        if value is not None:
                            return float(value)

            # Пробуем получить из adaptive_regime
            adaptive_regime = getattr(
                self.config_manager.scalping_config, "adaptive_regime", {}
            )
            if isinstance(adaptive_regime, dict) and regime:
                regime_config = adaptive_regime.get(regime, {})
                if isinstance(regime_config, dict):
                    # Для reversal_threshold ищем в reversal_detection
                    if param_name == "reversal_threshold":
                        reversal_config = regime_config.get("reversal_detection", {})
                        if isinstance(reversal_config, dict):
                            v_reversal = reversal_config.get("v_reversal_threshold")
                            if v_reversal is not None:
                                return float(v_reversal) / 100.0

                    value = regime_config.get(param_name)
                    if value is not None:
                        return float(value)

            # Пробуем получить из scalping_config
            value = getattr(self.config_manager.scalping_config, param_name, None)
            if value is not None:
                return float(value)

        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить {param_name} из конфига: {e}")

        return fallback

    def _get_regime_factor(
        self, param_name: str, regime: Optional[str], symbol: str
    ) -> float:
        """Получить фактор режима"""
        if not regime:
            regime = self._get_current_regime(symbol)

        # Факторы по режимам (из конфига или дефолтные)
        factors = {
            "reversal_threshold": {
                "trending": 0.2,
                "ranging": 0.0,
                "choppy": -0.2,
            },
            "adx_threshold": {
                "trending": 0.15,
                "ranging": -0.15,
                "choppy": -0.25,
            },
            "correlation_threshold": {
                "trending": -0.1,
                "ranging": -0.15,
                "choppy": -0.2,
            },
            "min_signal_strength": {
                "trending": -0.1,
                "ranging": 0.0,
                "choppy": 0.1,
            },
            "macd_divisor": {
                "trending": -0.15,
                "ranging": 0.15,
                "choppy": 0.25,
            },
            "strength_multiplier": {
                "trending": 0.15,
                "ranging": -0.1,
                "choppy": -0.15,
            },
        }

        param_factors = factors.get(param_name, {})
        return param_factors.get(regime, 0.0)

    async def _get_volatility_factor(self, param_name: str, symbol: str) -> float:
        """Получить фактор волатильности"""
        try:
            # ✅ ИСПРАВЛЕНО: Используем get_indicators() вместо несуществующего get_atr()
            indicators = await self.data_registry.get_indicators(symbol)
            if not indicators:
                return 0.0

            atr = indicators.get("atr", 0.0)
            if not atr or atr <= 0:
                return 0.0

            # ✅ ИСПРАВЛЕНО: Используем get_price() вместо несуществующего get_current_price()
            current_price = await self.data_registry.get_price(symbol)
            if not current_price or current_price <= 0:
                return 0.0

            volatility_pct = (atr / current_price) * 100

            # Определяем уровень волатильности
            if volatility_pct > 3.0:
                vol_level = "high"
            elif volatility_pct < 1.0:
                vol_level = "low"
            else:
                vol_level = "medium"

            # Факторы по волатильности
            factors = {
                "reversal_threshold": {
                    "high": 0.3,
                    "medium": 0.0,
                    "low": -0.3,
                },
                "adx_threshold": {
                    "high": -0.2,
                    "medium": 0.0,
                    "low": 0.2,
                },
                "macd_divisor": {
                    "high": -0.25,
                    "medium": 0.0,
                    "low": 0.25,
                },
                "strength_multiplier": {
                    "high": 0.25,
                    "medium": 0.0,
                    "low": -0.15,
                },
            }

            param_factors = factors.get(param_name, {})
            return param_factors.get(vol_level, 0.0)

        except Exception as e:
            logger.debug(f"⚠️ Ошибка получения волатильности для {symbol}: {e}")
            return 0.0

    def _get_winrate_factor(self, param_name: str, symbol: str) -> float:
        """Получить фактор win rate"""
        try:
            if not self.trading_statistics:
                return 0.0

            # ✅ ИСПРАВЛЕНО: Используем get_win_rate() вместо несуществующего get_symbol_stats()
            win_rate = self.trading_statistics.get_win_rate(regime=None, symbol=symbol)

            # ✅ ВАЖНО: Проверяем что win_rate это число
            if not isinstance(win_rate, (int, float)):
                win_rate = 0.5  # Fallback

            # Определяем уровень win rate
            if win_rate > 0.6:
                wr_level = "high"
            elif win_rate < 0.4:
                wr_level = "low"
            else:
                wr_level = "medium"

            # Факторы по win rate
            factors = {
                "reversal_threshold": {
                    "high": -0.2,
                    "medium": 0.0,
                    "low": 0.2,
                },
                "adx_threshold": {
                    "high": -0.15,
                    "medium": 0.0,
                    "low": 0.15,
                },
                "correlation_threshold": {
                    "high": -0.1,
                    "medium": 0.0,
                    "low": 0.1,
                },
                "min_signal_strength": {
                    "high": -0.15,
                    "medium": 0.0,
                    "low": 0.15,
                },
            }

            param_factors = factors.get(param_name, {})
            return param_factors.get(wr_level, 0.0)

        except Exception as e:
            logger.debug(f"⚠️ Ошибка получения win rate для {symbol}: {e}")
            return 0.0

    def _get_current_regime(self, symbol: str) -> str:
        """Получить текущий режим для символа"""
        try:
            if self.regime_manager:
                regime = self.regime_manager.get_current_regime(symbol)
                if regime:
                    return regime.value.lower()
        except Exception:
            pass

        return "ranging"  # Fallback

    def clear_cache(self):
        """Очистить кэш (для тестирования)"""
        self._cache.clear()
