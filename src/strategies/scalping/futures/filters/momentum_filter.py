"""
Momentum Filter для OKX Futures.
Фильтр на основе статьи Momentum Trading Strategy.
"""

from typing import Dict, List, Optional, Tuple

from loguru import logger

from src.models import OHLCV


class MomentumFilter:
    """
    Фильтр для проверки критериев Momentum Trading из статьи.

    Проверяет:
    - Отклоняет вертикальные скачки (vertical spikes)
    - Проверяет медленное движение к уровню (grind into level)
    - Проверяет постоянный рост объема
    - Проверяет лестничное движение (staircase action)
    """

    def __init__(self, config: Dict):
        """
        Инициализация Momentum Filter

        Args:
            config: Конфигурация фильтра из config_futures.yaml
        """
        self.config = config
        self.enabled = config.get("enabled", True)
        self.reject_vertical_spikes = config.get("reject_vertical_spikes", True)
        self.max_spike_percent = config.get("max_spike_percent", 1.0) / 100.0
        self.spike_lookback_periods = config.get("spike_lookback_periods", 5)
        self.check_grind_into_level = config.get("check_grind_into_level", True)
        self.grind_lookback_periods = config.get("grind_lookback_periods", 20)
        self.max_price_velocity_percent = (
            config.get("max_price_velocity_percent", 0.5) / 100.0
        )
        self.check_volume_increasing = config.get("check_volume_increasing", True)
        self.volume_increase_periods = config.get("volume_increase_periods", 10)
        self.check_staircase_action = config.get("check_staircase_action", True)
        self.min_staircase_duration_hours = config.get(
            "min_staircase_duration_hours", 2
        )
        self.reject_decreasing_volume = config.get("reject_decreasing_volume", True)
        self.reject_choppy_action = config.get("reject_choppy_action", True)
        # ✅ АДАПТИВНО: Пороги для каждого режима рынка
        self.thresholds_config = config.get("thresholds", {})

    async def evaluate(
        self,
        symbol: str,
        candles: List[OHLCV],
        current_price: float,
        level: Optional[float] = None,
        market_regime: Optional[
            str
        ] = None,  # ✅ АДАПТИВНО: Режим рынка для адаптации порогов
    ) -> Tuple[bool, Optional[str]]:
        """
        Проверяет критерии импульсной сделки из статьи.

        Args:
            symbol: Символ торговой пары
            candles: Список свечей
            current_price: Текущая цена
            level: Уровень (пивот, поддержка/сопротивление)

        Returns:
            (is_valid, reason) - True если все критерии выполнены
        """
        if not self.enabled:
            return True, None

        # 1. Проверка вертикальных скачков
        if self.reject_vertical_spikes:
            has_spike = self._has_vertical_spike(candles, current_price)
            if has_spike:
                return False, "Vertical spike detected - reject signal"

        # 2. Проверка медленного движения к уровню
        if self.check_grind_into_level and level is not None:
            is_grind = self._check_grind_into_level(candles, level, market_regime)
            if not is_grind:
                return False, "Fast movement to level - not a grind"

        # 3. Проверка постоянного роста объема
        if self.check_volume_increasing:
            is_increasing = self._check_volume_increasing(candles, market_regime)
            if not is_increasing:
                if self.reject_decreasing_volume:
                    return False, "Volume not consistently increasing"
                logger.debug(
                    f"⚠️ Volume not increasing for {symbol}, but allowing signal"
                )

        # 4. Проверка лестничного движения
        if self.check_staircase_action:
            has_staircase = self._check_staircase_action(candles, market_regime)
            if not has_staircase:
                if self.reject_choppy_action:
                    return False, "No staircase pattern detected"
                logger.debug(
                    f"⚠️ No staircase pattern for {symbol}, but allowing signal"
                )

        return True, "All momentum criteria met"

    def _has_vertical_spike(self, candles: List[OHLCV], current_price: float) -> bool:
        """Проверяет наличие вертикального скачка."""
        if len(candles) < self.spike_lookback_periods:
            return False

        recent_candles = candles[-self.spike_lookback_periods :]
        for candle in recent_candles:
            body_size = abs(candle.close - candle.open) / candle.open
            if body_size > self.max_spike_percent:
                logger.debug(
                    f"🚫 Vertical spike detected: body_size={body_size:.3%}, "
                    f"max={self.max_spike_percent:.3%}"
                )
                return True  # Вертикальный скачок обнаружен

        return False

    def _check_grind_into_level(
        self, candles: List[OHLCV], level: float, market_regime: Optional[str] = None
    ) -> bool:
        """Проверяет, что цена медленно приближается к уровню (не вертикальный скачок)."""
        if len(candles) < self.grind_lookback_periods:
            return False  # Недостаточно данных

        recent_candles = candles[-self.grind_lookback_periods :]

        # Рассчитываем скорость приближения к уровню
        distances = []
        for candle in recent_candles:
            distance = abs(candle.close - level) / level
            distances.append(distance)

        # Проверяем, что расстояние уменьшается постепенно (не резко)
        # Коэффициент вариации расстояний должен быть не слишком высоким
        if len(distances) < 3:
            return False

        avg_distance = sum(distances) / len(distances)
        variance = sum((d - avg_distance) ** 2 for d in distances) / len(distances)
        std_dev = variance**0.5
        cv = std_dev / avg_distance if avg_distance > 0 else 0

        # ✅ АДАПТИВНО: Максимальный коэффициент вариации из конфига по режиму
        # Получаем пороги для текущего режима
        regime_thresholds = (
            self.thresholds_config.get(market_regime, {}) if market_regime else {}
        )
        max_cv = regime_thresholds.get("max_cv", 0.5)  # Fallback: 0.5
        is_grind = cv <= max_cv

        if not is_grind:
            logger.debug(f"🚫 Fast movement to level: cv={cv:.3f}, max={max_cv:.3f}")

        return is_grind

    def _check_volume_increasing(
        self, candles: List[OHLCV], market_regime: Optional[str] = None
    ) -> bool:
        """Проверяет, что объем постоянно увеличивается."""
        if len(candles) < self.volume_increase_periods:
            return False  # Недостаточно данных

        volumes = [c.volume for c in candles[-self.volume_increase_periods :]]

        # Проверяем тренд объема (объем должен расти)
        increasing_count = 0
        for i in range(1, len(volumes)):
            if volumes[i] > volumes[i - 1]:
                increasing_count += 1

        # ✅ АДАПТИВНО: Минимальный ratio из конфига по режиму
        regime_thresholds = (
            self.thresholds_config.get(market_regime, {}) if market_regime else {}
        )
        min_increasing_ratio = regime_thresholds.get(
            "min_increasing_ratio", 0.6
        )  # Fallback: 0.6
        increasing_ratio = (
            increasing_count / (len(volumes) - 1) if len(volumes) > 1 else 0
        )

        is_increasing = increasing_ratio >= min_increasing_ratio

        if not is_increasing:
            logger.debug(
                f"🚫 Volume not increasing: ratio={increasing_ratio:.2%}, "
                f"min={min_increasing_ratio:.2%}"
            )

        return is_increasing

    def _check_staircase_action(
        self, candles: List[OHLCV], market_regime: Optional[str] = None
    ) -> bool:
        """Проверяет наличие лестничного движения (staircase pattern)."""
        # Предполагаем 1-минутные свечи
        min_candles = int(self.min_staircase_duration_hours * 60)

        if len(candles) < min_candles:
            return False  # Недостаточно данных

        recent_candles = candles[-min_candles:]

        # Проверяем наличие паттерна "лестницы":
        # - Постепенные повышения с откатами
        # - Больше повышений, чем падений
        higher_closes = 0
        lower_closes = 0

        for i in range(1, len(recent_candles)):
            if recent_candles[i].close > recent_candles[i - 1].close:
                higher_closes += 1
            elif recent_candles[i].close < recent_candles[i - 1].close:
                lower_closes += 1

        # Проверяем соотношение повышений к падениям
        total_changes = higher_closes + lower_closes
        if total_changes == 0:
            return False

        ratio = higher_closes / total_changes
        # ✅ АДАПТИВНО: Минимальный ratio из конфига по режиму
        regime_thresholds = (
            self.thresholds_config.get(market_regime, {}) if market_regime else {}
        )
        min_ratio = regime_thresholds.get("min_ratio", 0.6)  # Fallback: 0.6

        has_staircase = ratio >= min_ratio

        if not has_staircase:
            logger.debug(
                f"🚫 No staircase pattern: ratio={ratio:.2%}, "
                f"min={min_ratio:.2%}, higher={higher_closes}, lower={lower_closes}"
            )

        return has_staircase
