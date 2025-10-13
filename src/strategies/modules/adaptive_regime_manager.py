"""
Adaptive Regime Manager - динамическое переключение параметров стратегии.

Определяет текущий режим рынка (TRENDING, RANGING, CHOPPY) и автоматически
адаптирует параметры торговли для максимальной эффективности.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

from loguru import logger

from src.models import OHLCV


class RegimeType(Enum):
    """Типы рыночных режимов."""

    TRENDING = "trending"  # Трендовый рынок (направленное движение)
    RANGING = "ranging"  # Боковой рынок (диапазон)
    CHOPPY = "choppy"  # Хаотичный рынок (высокая волатильность)


@dataclass
class RegimeParameters:
    """Параметры торговли для конкретного режима."""

    # Scoring
    min_score_threshold: int
    # Trade frequency
    max_trades_per_hour: int
    # Position sizing
    position_size_multiplier: float
    # Exit levels
    tp_atr_multiplier: float
    sl_atr_multiplier: float
    # Risk management
    cooldown_after_loss_minutes: int
    # Module bonuses
    pivot_bonus_multiplier: float  # Усиление бонусов от Pivot Points
    volume_profile_bonus_multiplier: float  # Усиление бонусов от Volume Profile


@dataclass
class RegimeConfig:
    """Конфигурация Adaptive Regime Manager."""

    enabled: bool = True
    # Параметры детекции
    trending_adx_threshold: float = 25.0  # ADX >25 = тренд
    ranging_adx_threshold: float = 20.0  # ADX <20 = боковик
    high_volatility_threshold: float = 0.05  # >5% = высокая волатильность
    low_volatility_threshold: float = 0.02  # <2% = низкая волатильность
    trend_strength_percent: float = 2.0  # Цена >2% от SMA = тренд
    # Защита от частого переключения
    min_regime_duration_minutes: int = 15  # Минимум 15 мин в одном режиме
    required_confirmations: int = 3  # Нужно 3 подтверждения для переключения
    # Параметры для каждого режима
    trending_params: RegimeParameters = None
    ranging_params: RegimeParameters = None
    choppy_params: RegimeParameters = None


@dataclass
class RegimeDetectionResult:
    """Результат определения режима рынка."""

    regime: RegimeType
    confidence: float  # 0.0-1.0
    indicators: Dict[str, float]  # Значения индикаторов для логирования
    reason: str  # Объяснение почему этот режим


class AdaptiveRegimeManager:
    """
    Управляет адаптацией параметров стратегии к рыночным условиям.

    Определяет текущий режим рынка (TRENDING/RANGING/CHOPPY) и автоматически
    переключает параметры торговли для оптимальной производительности.
    """

    def __init__(self, config: RegimeConfig):
        self.config = config
        # Текущий режим
        self.current_regime: RegimeType = RegimeType.RANGING  # По умолчанию
        self.regime_start_time: datetime = datetime.utcnow()
        self.last_regime_check: datetime = datetime.utcnow()
        # История для подтверждений
        self.regime_confirmations: List[RegimeType] = []
        # Статистика
        self.regime_switches: Dict[str, int] = {}
        self.time_in_regime: Dict[RegimeType, timedelta] = {
            RegimeType.TRENDING: timedelta(0),
            RegimeType.RANGING: timedelta(0),
            RegimeType.CHOPPY: timedelta(0),
        }

        logger.info(
            f"ARM initialized: ADX trend={config.trending_adx_threshold}, "
            f"volatility={config.low_volatility_threshold:.1%}-{config.high_volatility_threshold:.1%}"
        )

    def detect_regime(
        self, candles: List[OHLCV], current_price: float
    ) -> RegimeDetectionResult:
        """
        Определяет текущий режим рынка на основе технических индикаторов.

        Args:
            candles: Список исторических свечей (минимум 50)
            current_price: Текущая цена

        Returns:
            RegimeDetectionResult с типом режима и уверенностью
        """
        if len(candles) < 50:
            return RegimeDetectionResult(
                regime=self.current_regime,
                confidence=0.0,
                indicators={},
                reason="Insufficient data (need 50+ candles)",
            )

        # Рассчитываем индикаторы для детекции
        indicators = self._calculate_regime_indicators(candles, current_price)

        # Определяем режим на основе индикаторов
        regime, confidence, reason = self._classify_regime(indicators)

        return RegimeDetectionResult(
            regime=regime, confidence=confidence, indicators=indicators, reason=reason
        )

    def _calculate_regime_indicators(
        self, candles: List[OHLCV], current_price: float
    ) -> Dict[str, float]:
        """Рассчитывает индикаторы для определения режима."""
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        # SMA для определения тренда
        sma_20 = sum(closes[-20:]) / 20
        sma_50 = sum(closes[-50:]) / 50

        # Волатильность (ATR упрощенный)
        true_ranges = []
        for i in range(1, len(candles)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            true_ranges.append(max(high_low, high_close, low_close))

        atr = sum(true_ranges[-14:]) / 14 if len(true_ranges) >= 14 else 0
        volatility_percent = (atr / current_price) * 100 if current_price > 0 else 0

        # ADX (упрощенный - направленность движения)
        # Используем разницу между High-Low за период
        directional_movement = sum(
            [abs(highs[i] - lows[i]) for i in range(-14, 0)]
        )
        total_movement = sum([highs[i] - lows[i] for i in range(-14, 0)])
        adx_proxy = (directional_movement / total_movement * 100) if total_movement > 0 else 0

        # Trend strength (отклонение от SMA)
        trend_deviation = ((current_price - sma_50) / sma_50) * 100

        # Range detection (цена в узком диапазоне?)
        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])
        range_width = ((recent_high - recent_low) / recent_low) * 100

        # Количество разворотов (для choppy)
        reversals = 0
        for i in range(-20, -1):
            if i > -20:
                prev_direction = closes[i - 1] > closes[i - 2]
                curr_direction = closes[i] > closes[i - 1]
                if prev_direction != curr_direction:
                    reversals += 1

        return {
            "sma_20": sma_20,
            "sma_50": sma_50,
            "current_price": current_price,
            "atr": atr,
            "volatility_percent": volatility_percent,
            "adx_proxy": adx_proxy,
            "trend_deviation": abs(trend_deviation),
            "range_width": range_width,
            "reversals": reversals,
        }

    def _classify_regime(
        self, indicators: Dict[str, float]
    ) -> tuple[RegimeType, float, str]:
        """
        Классифицирует режим рынка на основе индикаторов.

        Returns:
            (regime_type, confidence, reason)
        """
        vol = indicators["volatility_percent"]
        trend_dev = indicators["trend_deviation"]
        adx = indicators["adx_proxy"]
        range_width = indicators["range_width"]
        reversals = indicators["reversals"]

        # CHOPPY: Высокая волатильность + много разворотов
        if vol > self.config.high_volatility_threshold and reversals > 10:
            confidence = min(1.0, (vol / 0.1) * 0.5 + (reversals / 20) * 0.5)
            reason = (
                f"High volatility ({vol:.2%}) + {reversals} reversals "
                f"→ Chaotic market"
            )
            return RegimeType.CHOPPY, confidence, reason

        # TRENDING: Сильный тренд + направленное движение
        if (
            trend_dev > self.config.trend_strength_percent
            and adx > self.config.trending_adx_threshold
        ):
            confidence = min(
                1.0, (trend_dev / 5.0) * 0.6 + (adx / 50.0) * 0.4
            )
            reason = (
                f"Strong trend (deviation {trend_dev:.2%}, ADX {adx:.1f}) "
                f"→ Trending market"
            )
            return RegimeType.TRENDING, confidence, reason

        # RANGING: Узкий диапазон + слабый тренд
        if (
            range_width < 3.0
            and trend_dev < self.config.trend_strength_percent
            and adx < self.config.ranging_adx_threshold
        ):
            confidence = min(1.0, (3.0 - range_width) / 3.0)
            reason = (
                f"Narrow range ({range_width:.2%}), weak trend (ADX {adx:.1f}) "
                f"→ Ranging market"
            )
            return RegimeType.RANGING, confidence, reason

        # По умолчанию: RANGING (безопасный режим)
        return (
            RegimeType.RANGING,
            0.5,
            "No clear regime detected → default to RANGING",
        )

    def update_regime(
        self, candles: List[OHLCV], current_price: float
    ) -> Optional[RegimeType]:
        """
        Обновляет текущий режим с защитой от частых переключений.

        Returns:
            Новый режим если произошло переключение, иначе None
        """
        # Определяем новый режим
        detection = self.detect_regime(candles, current_price)

        # Добавляем в историю подтверждений
        self.regime_confirmations.append(detection.regime)
        # Храним только последние N подтверждений
        if len(self.regime_confirmations) > self.config.required_confirmations:
            self.regime_confirmations.pop(0)

        # Проверяем нужно ли переключение
        new_regime = self._should_switch_regime(detection)

        if new_regime and new_regime != self.current_regime:
            # Обновляем статистику времени
            time_in_current = datetime.utcnow() - self.regime_start_time
            self.time_in_regime[self.current_regime] += time_in_current

            # Логируем переключение
            self._log_regime_switch(
                old=self.current_regime, new=new_regime, detection=detection
            )

            # Переключаем режим
            self.current_regime = new_regime
            self.regime_start_time = datetime.utcnow()
            self.regime_confirmations.clear()

            # Статистика переключений
            switch_key = f"{self.current_regime.value} → {new_regime.value}"
            self.regime_switches[switch_key] = (
                self.regime_switches.get(switch_key, 0) + 1
            )

            return new_regime

        return None

    def _should_switch_regime(
        self, detection: RegimeDetectionResult
    ) -> Optional[RegimeType]:
        """
        Проверяет нужно ли переключение режима с защитами.

        Returns:
            Новый режим или None если переключение не нужно
        """
        # Проверка 1: Минимальное время в текущем режиме
        time_in_current = datetime.utcnow() - self.regime_start_time
        if time_in_current < timedelta(
            minutes=self.config.min_regime_duration_minutes
        ):
            # Исключение: CHOPPY режим может включиться немедленно (защита!)
            if detection.regime != RegimeType.CHOPPY or detection.confidence < 0.8:
                return None

        # Проверка 2: Достаточно подтверждений?
        if len(self.regime_confirmations) < self.config.required_confirmations:
            return None

        # Проверка 3: Все последние N проверок указывают на новый режим?
        if all(r == detection.regime for r in self.regime_confirmations):
            return detection.regime

        return None

    def get_current_parameters(self) -> RegimeParameters:
        """
        Возвращает параметры для текущего режима.

        Returns:
            RegimeParameters с настройками для активного режима
        """
        if self.current_regime == RegimeType.TRENDING:
            return self.config.trending_params
        elif self.current_regime == RegimeType.RANGING:
            return self.config.ranging_params
        else:  # CHOPPY
            return self.config.choppy_params

    def _log_regime_switch(
        self,
        old: RegimeType,
        new: RegimeType,
        detection: RegimeDetectionResult,
    ) -> None:
        """Логирует переключение режима."""
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🔄 MARKET REGIME SWITCH")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"   Old regime: {old.value.upper()}")
        logger.info(f"   New regime: {new.value.upper()}")
        logger.info(f"   Confidence: {detection.confidence:.1%}")
        logger.info(f"   Reason: {detection.reason}")
        logger.info("")
        logger.info("📊 Market Indicators:")
        for key, value in detection.indicators.items():
            if "percent" in key or "volatility" in key or "deviation" in key:
                logger.info(f"   {key}: {value:.3%}")
            else:
                logger.info(f"   {key}: {value:.2f}")
        logger.info("")

        # Логируем новые параметры
        params = self.get_current_parameters()
        logger.info("⚙️ New Parameters:")
        logger.info(f"   Score threshold: {params.min_score_threshold}/12")
        logger.info(f"   Max trades/hour: {params.max_trades_per_hour}")
        logger.info(f"   Position size: {params.position_size_multiplier}x")
        logger.info(f"   TP: {params.tp_atr_multiplier} ATR")
        logger.info(f"   SL: {params.sl_atr_multiplier} ATR")
        logger.info(
            f"   Cooldown after loss: {params.cooldown_after_loss_minutes} min"
        )
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def get_statistics(self) -> Dict[str, any]:
        """
        Возвращает статистику работы ARM.

        Returns:
            Словарь со статистикой режимов и переключений
        """
        total_time = sum(
            [td.total_seconds() for td in self.time_in_regime.values()],
            start=0.0,
        )

        time_distribution = {}
        if total_time > 0:
            for regime, td in self.time_in_regime.items():
                time_distribution[regime.value] = (
                    td.total_seconds() / total_time * 100
                )

        return {
            "current_regime": self.current_regime.value,
            "time_in_current_regime": str(
                datetime.utcnow() - self.regime_start_time
            ),
            "total_switches": sum(self.regime_switches.values()),
            "switches_by_type": self.regime_switches,
            "time_distribution": time_distribution,
        }

    def log_statistics(self) -> None:
        """Выводит статистику в лог."""
        stats = self.get_statistics()

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("📊 ADAPTIVE REGIME MANAGER STATISTICS")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"Current regime: {stats['current_regime'].upper()}")
        logger.info(f"Time in current: {stats['time_in_current_regime']}")
        logger.info(f"Total switches: {stats['total_switches']}")

        if stats["time_distribution"]:
            logger.info("\nTime distribution:")
            for regime, percent in stats["time_distribution"].items():
                logger.info(f"  {regime.upper()}: {percent:.1f}%")

        if stats["switches_by_type"]:
            logger.info("\nRegime switches:")
            for switch, count in sorted(
                stats["switches_by_type"].items(), key=lambda x: x[1], reverse=True
            ):
                logger.info(f"  {switch}: {count} times")

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

