"""
Adaptive Regime Manager - динамическое переключение параметров стратегии.

Определяет текущий режим рынка (TRENDING, RANGING, CHOPPY) и автоматически
адаптирует параметры торговли для максимальной эффективности.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

from loguru import logger

from src.models import OHLCV
from src.strategies.scalping.futures.indicators.fast_adx import FastADX


class RegimeType(Enum):
    """Типы рыночных режимов."""

    TRENDING = "trending"  # Трендовый рынок (направленное движение)
    RANGING = "ranging"  # Боковой рынок (диапазон)
    CHOPPY = "choppy"  # Хаотичный рынок (высокая волатильность)


@dataclass
class IndicatorParameters:
    """Параметры индикаторов для конкретного режима."""

    rsi_overbought: float
    rsi_oversold: float
    volume_threshold: float
    sma_fast: int
    sma_slow: int
    ema_fast: int
    ema_slow: int
    atr_period: int
    min_volatility_atr: float


@dataclass
class ModuleParameters:
    """Параметры модулей для конкретного режима."""

    # Multi-Timeframe
    mtf_block_opposite: bool
    mtf_score_bonus: int
    mtf_confirmation_timeframe: str

    # Correlation Filter
    correlation_threshold: float
    max_correlated_positions: int
    block_same_direction_only: bool

    # Time Filter
    prefer_overlaps: bool
    avoid_low_liquidity_hours: bool

    # Pivot Points
    pivot_level_tolerance_percent: float
    pivot_score_bonus_near_level: int
    pivot_use_last_n_days: int

    # Volume Profile
    vp_score_bonus_in_value_area: int
    vp_score_bonus_near_poc: int
    vp_poc_tolerance_percent: float
    vp_lookback_candles: int

    # 🆕 ADX Filter (сила тренда)
    adx_threshold: float = 25.0  # Минимальная сила тренда
    adx_di_difference: float = 5.0  # Разница между +DI и -DI

    # Time Filter (с default значением в конце)
    avoid_weekends: bool = True  # По умолчанию для всех режимов


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
    max_holding_minutes: int  # Максимальное время удержания позиции
    # Risk management
    cooldown_after_loss_minutes: int
    # Module bonuses
    pivot_bonus_multiplier: float  # Усиление бонусов от Pivot Points
    volume_profile_bonus_multiplier: float  # Усиление бонусов от Volume Profile

    # НОВОЕ: Параметры индикаторов и модулей
    indicators: IndicatorParameters
    modules: ModuleParameters

    # ✨ НОВОЕ (18.10.2025): Profit Harvesting (адаптивный под режим)
    # ВАЖНО: Поля с default значениями ПОСЛЕ обязательных!
    ph_enabled: bool = True  # Включен ли Profit Harvesting
    ph_threshold: float = 0.20  # Минимальный профит в USD для досрочного закрытия
    ph_time_limit: int = 120  # Максимальное время (сек) для PH


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
    # ⚠️ ВАЖНО: Эти дефолты используются ТОЛЬКО как fallback если конфиг не загружен!
    # В реальной работе параметры загружаются из config.yaml через signal_generator
    trending_params: RegimeParameters = field(
        default_factory=lambda: RegimeParameters(
            min_score_threshold=3.0,  # Должен быть переопределен из config.yaml!
            max_trades_per_hour=15,
            position_size_multiplier=1.2,
            tp_atr_multiplier=2.5,
            sl_atr_multiplier=1.2,
            max_holding_minutes=20,
            cooldown_after_loss_minutes=3,
            pivot_bonus_multiplier=1.2,
            volume_profile_bonus_multiplier=1.1,
            indicators={},
            modules={},
        )
    )
    ranging_params: RegimeParameters = field(
        default_factory=lambda: RegimeParameters(
            min_score_threshold=4.0,  # ⚠️ ЗАХАРДКОЖЕН! Должен быть переопределен из config.yaml (там min_score_threshold=2)!
            max_trades_per_hour=10,
            position_size_multiplier=1.0,
            tp_atr_multiplier=2.0,
            sl_atr_multiplier=1.5,
            max_holding_minutes=15,
            cooldown_after_loss_minutes=5,
            pivot_bonus_multiplier=1.0,
            volume_profile_bonus_multiplier=1.0,
            indicators={},
            modules={},
        )
    )
    choppy_params: RegimeParameters = field(
        default_factory=lambda: RegimeParameters(
            min_score_threshold=5.0,  # Должен быть переопределен из config.yaml!
            max_trades_per_hour=8,
            position_size_multiplier=0.8,
            tp_atr_multiplier=1.5,
            sl_atr_multiplier=2.0,
            max_holding_minutes=10,
            cooldown_after_loss_minutes=8,
            pivot_bonus_multiplier=0.8,
            volume_profile_bonus_multiplier=0.9,
            indicators={},
            modules={},
        )
    )


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

    def __init__(
        self,
        config: RegimeConfig,
        trading_statistics=None,
        data_registry=None,
        symbol=None,
    ):
        self.config = config
        # Текущий режим
        self.current_regime: RegimeType = RegimeType.RANGING  # По умолчанию
        self.regime_start_time: datetime = datetime.utcnow()
        self.last_regime_check: datetime = datetime.utcnow()
        # История для подтверждений
        self.regime_confirmations: List[RegimeType] = []
        # Статистика
        self.regime_switches: Dict[str, int] = {}
        # ✅ НОВОЕ: Модуль статистики для динамической адаптации
        self.trading_statistics = trading_statistics
        # ✅ НОВОЕ: DataRegistry для сохранения режимов
        self.data_registry = data_registry
        # ✅ НОВОЕ: Символ для этого RegimeManager (если per-symbol)
        self.symbol = symbol
        self.time_in_regime: Dict[RegimeType, timedelta] = {
            RegimeType.TRENDING: timedelta(0),
            RegimeType.RANGING: timedelta(0),
            RegimeType.CHOPPY: timedelta(0),
        }

        # ✅ FastADX для настоящего расчета ADX вместо ADX Proxy
        adx_period = getattr(config, "adx_period", 9)
        self.fast_adx = FastADX(
            period=adx_period, threshold=config.trending_adx_threshold
        )

        logger.info(
            f"ARM initialized: ADX trend={config.trending_adx_threshold}, "
            f"volatility={config.low_volatility_threshold:.1%}-{config.high_volatility_threshold:.1%}, "
            f"FastADX period={adx_period}"
        )

    def set_data_registry(self, data_registry, symbol=None):
        """
        ✅ НОВОЕ: Установить DataRegistry для сохранения режимов.

        Args:
            data_registry: Экземпляр DataRegistry
            symbol: Символ для этого RegimeManager (опционально, переопределяет self.symbol)
        """
        self.data_registry = data_registry
        if symbol is not None:
            self.symbol = symbol
        logger.debug(f"✅ RegimeManager: DataRegistry установлен (symbol={self.symbol})")

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

        # 🔍 DEBUG: Логируем детекцию режима
        adx_val = indicators.get("adx", indicators.get("adx_proxy", 0))
        di_plus = indicators.get("di_plus", 0)
        di_minus = indicators.get("di_minus", 0)
        trend_dir = indicators.get("trend_direction", "N/A")
        vol_ratio = indicators.get("volume_ratio", 1.0)
        volatility = indicators.get("volatility_percent", 0)
        # ✅ Ограничиваем вывод volatility (если >100% значит ошибка)
        volatility_str = (
            f"{volatility:.2%}" if volatility <= 100 else f"{volatility:.0f}% (ERROR!)"
        )
        logger.debug(
            f"🧠 ARM Detect Regime:\n"
            f"   Detected: {regime.value.upper()} (confidence: {confidence:.1%})\n"
            f"   Reason: {reason}\n"
            f"   ADX: {adx_val:.1f} (+DI={di_plus:.1f}, -DI={di_minus:.1f}, direction={trend_dir})\n"
            f"   Volatility: {volatility_str}\n"
            f"   Volume Ratio: {vol_ratio:.2f}x\n"
            f"   Reversals: {indicators.get('reversals', 0)}"
        )

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

        # ✅ ИСПОЛЬЗУЕМ НАСТОЯЩИЙ ADX через FastADX вместо ADX Proxy
        # Обновляем FastADX с историческими данными
        for candle in candles[-self.fast_adx.period :]:
            self.fast_adx.update(high=candle.high, low=candle.low, close=candle.close)

        # Получаем настоящий ADX и +DI/-DI
        adx_value = self.fast_adx.get_adx_value()
        di_plus = self.fast_adx.get_di_plus()
        di_minus = self.fast_adx.get_di_minus()
        trend_direction = (
            self.fast_adx.get_trend_direction()
        )  # "bullish"/"bearish"/"neutral"

        # Для обратной совместимости сохраняем как adx_proxy, но это теперь настоящий ADX
        adx_proxy = adx_value

        # ✅ Volume indicators для подтверждения режима
        volumes = [c.volume for c in candles]
        # Volume MA (20) - средний объем
        volume_ma = (
            sum(volumes[-20:]) / 20
            if len(volumes) >= 20
            else sum(volumes) / len(volumes)
            if volumes
            else 0
        )
        # Volume Ratio = текущий объем / средний объем
        current_volume = volumes[-1] if volumes else 0
        volume_ratio = current_volume / volume_ma if volume_ma > 0 else 1.0

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
            "adx_proxy": adx_proxy,  # Теперь это настоящий ADX
            "adx": adx_value,  # Добавляем явное значение ADX
            "di_plus": di_plus,  # +DI для направления тренда
            "di_minus": di_minus,  # -DI для направления тренда
            "trend_direction": trend_direction,  # "bullish"/"bearish"/"neutral"
            "trend_deviation": abs(trend_deviation),
            "range_width": range_width,
            "reversals": reversals,
            "volume_ma": volume_ma,  # Средний объем
            "volume_ratio": volume_ratio,  # Текущий объем / средний объем
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

        # CHOPPY: Высокая волатильность + много разворотов + высокий объем
        volume_ratio = indicators.get("volume_ratio", 1.0)
        # ✅ Высокий объем + хаос = choppy (не путать с trending!)
        has_choppy_volume = volume_ratio > 1.5  # Очень высокий объем + хаос

        if (
            vol > self.config.high_volatility_threshold
            and reversals > 10
            and has_choppy_volume
        ):
            confidence = min(
                1.0,
                (vol / 0.1) * 0.4
                + (reversals / 20) * 0.3
                + (0.3 if has_choppy_volume else 0),
            )
            reason = (
                f"High volatility ({vol:.2%}) + {reversals} reversals + "
                f"high volume ({volume_ratio:.2f}x) → Chaotic market"
            )
            return RegimeType.CHOPPY, confidence, reason

        # TRENDING: Сильный тренд + направленное движение + подтверждение объемом
        # ✅ ИСПОЛЬЗУЕМ НАСТОЯЩИЙ ADX и направление тренда (+DI/-DI)
        trend_direction = indicators.get("trend_direction", "neutral")
        di_plus = indicators.get("di_plus", 0)
        di_minus = indicators.get("di_minus", 0)
        volume_ratio = indicators.get("volume_ratio", 1.0)

        # Проверяем что есть направленность (+DI > -DI для bullish или -DI > +DI для bearish)
        has_direction = (trend_direction in ["bullish", "bearish"]) or (
            abs(di_plus - di_minus) > 5.0  # Разница между +DI и -DI > 5
        )

        # ✅ Проверяем подтверждение объемом (высокий объем = сильный тренд)
        has_volume_confirmation = volume_ratio > 1.2  # Объем выше среднего на 20%

        if (
            trend_dev > self.config.trend_strength_percent
            and adx > self.config.trending_adx_threshold
            and has_direction
            and has_volume_confirmation  # ✅ Добавили проверку объема
        ):
            confidence = min(
                1.0,
                (trend_dev / 5.0) * 0.3
                + (adx / 50.0) * 0.3
                + (0.2 if has_direction else 0)
                + (0.2 if has_volume_confirmation else 0),
            )
            trend_info = (
                f"({trend_direction}, +DI={di_plus:.1f}, -DI={di_minus:.1f})"
                if trend_direction != "neutral"
                else ""
            )
            reason = (
                f"Strong trend (deviation {trend_dev:.2%}, ADX {adx:.1f} {trend_info}, "
                f"volume={volume_ratio:.2f}x) → Trending market"
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

    async def update_regime(
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
            old_regime = self.current_regime
            self.current_regime = new_regime
            self.regime_start_time = datetime.utcnow()
            self.regime_confirmations.clear()

            # Статистика переключений
            switch_key = f"{old_regime.value} → {new_regime.value}"
            self.regime_switches[switch_key] = (
                self.regime_switches.get(switch_key, 0) + 1
            )

            # ✅ НОВОЕ: Сохраняем режим в DataRegistry после переключения
            if self.data_registry and self.symbol:
                try:
                    # Получаем параметры режима (если доступны)
                    regime_params = None
                    if hasattr(self.config, f"{new_regime.value.lower()}_params"):
                        regime_params_obj = getattr(
                            self.config, f"{new_regime.value.lower()}_params"
                        )
                        if regime_params_obj:
                            # Конвертируем RegimeParameters в dict
                            regime_params = {
                                "min_score_threshold": getattr(
                                    regime_params_obj, "min_score_threshold", None
                                ),
                                "max_trades_per_hour": getattr(
                                    regime_params_obj, "max_trades_per_hour", None
                                ),
                                "position_size_multiplier": getattr(
                                    regime_params_obj, "position_size_multiplier", None
                                ),
                                "tp_atr_multiplier": getattr(
                                    regime_params_obj, "tp_atr_multiplier", None
                                ),
                                "sl_atr_multiplier": getattr(
                                    regime_params_obj, "sl_atr_multiplier", None
                                ),
                                "max_holding_minutes": getattr(
                                    regime_params_obj, "max_holding_minutes", None
                                ),
                            }

                    await self.data_registry.update_regime(
                        symbol=self.symbol,
                        regime=new_regime.value.lower(),
                        params=regime_params,
                    )
                    logger.debug(
                        f"✅ DataRegistry: Обновлен режим для {self.symbol}: {old_regime.value} → {new_regime.value}"
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Ошибка сохранения режима в DataRegistry для {self.symbol}: {e}"
                    )

            return new_regime

        # ✅ НОВОЕ: Сохраняем текущий режим в DataRegistry даже если переключения не было
        # (для актуальности и первого определения режима)
        if self.data_registry and self.symbol:
            try:
                # Получаем параметры режима (если доступны)
                regime_params = None
                if hasattr(self.config, f"{self.current_regime.value.lower()}_params"):
                    regime_params_obj = getattr(
                        self.config, f"{self.current_regime.value.lower()}_params"
                    )
                    if regime_params_obj:
                        # Конвертируем RegimeParameters в dict
                        regime_params = {
                            "min_score_threshold": getattr(
                                regime_params_obj, "min_score_threshold", None
                            ),
                            "max_trades_per_hour": getattr(
                                regime_params_obj, "max_trades_per_hour", None
                            ),
                            "position_size_multiplier": getattr(
                                regime_params_obj, "position_size_multiplier", None
                            ),
                            "tp_atr_multiplier": getattr(
                                regime_params_obj, "tp_atr_multiplier", None
                            ),
                            "sl_atr_multiplier": getattr(
                                regime_params_obj, "sl_atr_multiplier", None
                            ),
                            "max_holding_minutes": getattr(
                                regime_params_obj, "max_holding_minutes", None
                            ),
                        }

                await self.data_registry.update_regime(
                    symbol=self.symbol,
                    regime=self.current_regime.value.lower(),
                    params=regime_params,
                )
                logger.debug(
                    f"✅ DataRegistry: Текущий режим для {self.symbol}: {self.current_regime.value}"
                )
            except Exception as e:
                logger.debug(
                    f"⚠️ Ошибка обновления режима в DataRegistry для {self.symbol}: {e}"
                )

        return None

    def get_current_regime(self) -> Optional[str]:
        """
        Получить текущий режим рынка в виде строки.

        Returns:
            Строка с текущим режимом: "trending", "ranging", "choppy" или None
        """
        if not hasattr(self, "current_regime") or self.current_regime is None:
            return None
        return self.current_regime.value.lower() if self.current_regime else None

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
        if time_in_current < timedelta(minutes=self.config.min_regime_duration_minutes):
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

    def calculate_dynamic_threshold(
        self, base_threshold: float, win_rate: float, volatility: Optional[float] = None
    ) -> float:
        """
        ✅ НОВОЕ: Расчет динамического порога на основе win rate и волатильности

        Args:
            base_threshold: Базовый порог (0-1)
            win_rate: Win rate (0-1)
            volatility: Волатильность (опционально, 0-1)

        Returns:
            Адаптированный порог (0-1)
        """
        multiplier = 1.0

        # Адаптация на основе win rate
        if win_rate < 0.3:
            # Низкий win rate - повышаем порог (строже фильтрация)
            multiplier = 1.3
        elif win_rate < 0.4:
            multiplier = 1.2
        elif win_rate < 0.5:
            multiplier = 1.1
        else:
            # Win rate >= 50% - можно снизить порог
            multiplier = 1.0

        # Адаптация на основе волатильности
        if volatility is not None:
            if volatility > 0.05:  # Высокая волатильность (>5%)
                multiplier *= 1.1  # Повышаем порог на 10%
            elif volatility < 0.02:  # Низкая волатильность (<2%)
                multiplier *= 0.95  # Слегка снижаем порог

        # Ограничиваем множитель (не ниже 0.5, не выше 2.0)
        multiplier = max(0.5, min(2.0, multiplier))

        return base_threshold * multiplier

    async def is_signal_valid(self, signal: Dict, market_data=None) -> bool:
        """
        Проверяет валидность сигнала для текущего режима.

        Args:
            signal: Торговый сигнал
            market_data: Рыночные данные (опционально)

        Returns:
            True если сигнал валиден для текущего режима
        """
        try:
            # Получаем параметры текущего режима
            regime_params = self.get_current_parameters()

            # Проверяем min_score_threshold
            signal_strength = signal.get("strength", 0)
            # ✅ ИСПРАВЛЕНИЕ: Нормализуем min_score_threshold к 0-1 диапазону
            # Но для ranging режима делаем более мягкую проверку (учитываем конфликтные сигналы)
            base_min_strength = regime_params.min_score_threshold / 12.0

            # ✅ НОВОЕ: Динамическая адаптация порога на основе статистики
            min_strength = base_min_strength
            if self.trading_statistics:
                regime_name = self.current_regime.value.lower()
                # ✅ ИСПРАВЛЕНО: Получаем статистику по символу и режиму
                symbol = signal.get("symbol")
                win_rate = self.trading_statistics.get_win_rate(regime_name, symbol)

                # Получаем волатильность из market_data если доступна
                volatility = None
                if (
                    market_data
                    and hasattr(market_data, "ohlcv_data")
                    and market_data.ohlcv_data
                ):
                    # Простой расчет волатильности как ATR / цена
                    try:
                        prices = [c.close for c in market_data.ohlcv_data[-20:]]
                        if len(prices) > 1:
                            price_changes = [
                                abs(prices[i] - prices[i - 1]) / prices[i - 1]
                                for i in range(1, len(prices))
                            ]
                            volatility = (
                                sum(price_changes) / len(price_changes)
                                if price_changes
                                else None
                            )
                    except:
                        pass

                # Рассчитываем динамический порог
                min_strength = self.calculate_dynamic_threshold(
                    base_min_strength, win_rate, volatility
                )

                logger.debug(
                    f"📊 Динамический порог для {regime_name}: "
                    f"base={base_min_strength:.3f}, win_rate={win_rate:.2%}, "
                    f"final={min_strength:.3f} (multiplier={min_strength/base_min_strength:.2f}x)"
                )

            # ✅ УМЯГЧЕНИЕ: Если сигнал с конфликтом (has_conflict), снижаем порог на 50%
            # Это позволит конфликтным сигналам проходить для быстрого скальпа
            has_conflict = signal.get("has_conflict", False)
            if has_conflict:
                min_strength *= 0.5  # Снижаем порог для конфликтных сигналов
                logger.debug(
                    f"⚡ Конфликтный сигнал: сниженный порог min={min_strength:.3f} "
                    f"(было {regime_params.min_score_threshold / 12.0:.3f})"
                )

            # ✅ ДОПОЛНИТЕЛЬНОЕ УМЯГЧЕНИЕ: Для ranging режима снижаем порог еще на 50%
            # Это позволит больше сигналов проходить в боковике (увеличено с 20% до 50%)
            if self.current_regime == RegimeType.RANGING:
                min_strength *= 0.5  # ✅ ИСПРАВЛЕНО: Увеличено снижение с 20% (0.8x) до 50% (0.5x) для ranging
                logger.debug(
                    f"📊 RANGING режим: дополнительное снижение порога до {min_strength:.3f}"
                )

            if signal_strength < min_strength:
                logger.debug(
                    f"🔍 Сигнал отфильтрован ARM: strength={signal_strength:.3f} < "
                    f"min={min_strength:.3f} (режим: {self.current_regime.value}"
                    f"{', конфликтный' if has_conflict else ''})"
                )
                return False

            # Дополнительные проверки по режиму
            if self.current_regime == RegimeType.CHOPPY:
                # В choppy режиме требуем больше подтверждений (выше confidence)
                confidence = signal.get("confidence", 0)
                if confidence < 0.7:  # Требуем минимум 70% уверенности
                    logger.debug(
                        f"🔍 Сигнал отфильтрован ARM (choppy): confidence={confidence:.2f} < 0.7"
                    )
                    return False

            return True

        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки сигнала в ARM: {e}")
            # В случае ошибки разрешаем сигнал (fail-open)
            return True

    def get_current_parameters(self, balance_manager=None) -> RegimeParameters:
        """
        Возвращает параметры для текущего режима с учетом адаптивного баланса.

        Args:
            balance_manager: AdaptiveBalanceManager для адаптации параметров

        Returns:
            RegimeParameters с настройками для активного режима (адаптированные под баланс)
        """
        # Получаем базовые параметры режима
        if self.current_regime == RegimeType.TRENDING:
            base_params = self.config.trending_params
        elif self.current_regime == RegimeType.RANGING:
            base_params = self.config.ranging_params
        else:  # CHOPPY
            base_params = self.config.choppy_params

        # Если есть balance_manager - применяем адаптацию
        if balance_manager and base_params:
            regime_type = (
                self.current_regime.value.lower()
            )  # "trending", "ranging", "choppy"
            adapted_params = balance_manager.apply_to_regime_params(
                base_params.__dict__, regime_type
            )

            # Создаем новый RegimeParameters с адаптированными значениями
            return RegimeParameters(
                min_score_threshold=adapted_params.get(
                    "min_score_threshold", base_params.min_score_threshold
                ),
                max_trades_per_hour=adapted_params.get(
                    "max_trades_per_hour", base_params.max_trades_per_hour
                ),
                position_size_multiplier=adapted_params.get(
                    "position_size_multiplier", base_params.position_size_multiplier
                ),
                tp_atr_multiplier=adapted_params.get(
                    "tp_atr_multiplier", base_params.tp_atr_multiplier
                ),
                sl_atr_multiplier=adapted_params.get(
                    "sl_atr_multiplier", base_params.sl_atr_multiplier
                ),
                max_holding_minutes=adapted_params.get(
                    "max_holding_minutes", base_params.max_holding_minutes
                ),
                cooldown_after_loss_minutes=adapted_params.get(
                    "cooldown_after_loss_minutes",
                    base_params.cooldown_after_loss_minutes,
                ),
                pivot_bonus_multiplier=adapted_params.get(
                    "pivot_bonus_multiplier", base_params.pivot_bonus_multiplier
                ),
                volume_profile_bonus_multiplier=adapted_params.get(
                    "volume_profile_bonus_multiplier",
                    base_params.volume_profile_bonus_multiplier,
                ),
                indicators=base_params.indicators,
                modules=base_params.modules,
            )

        # Если нет balance_manager или base_params - возвращаем базовые параметры
        if base_params:
            return base_params
        else:
            # Fallback - создаем дефолтные параметры
            return RegimeParameters(
                min_score_threshold=4.0,
                max_trades_per_hour=10,
                position_size_multiplier=1.0,
                tp_atr_multiplier=2.0,
                sl_atr_multiplier=1.5,
                max_holding_minutes=15,
                cooldown_after_loss_minutes=5,
                pivot_bonus_multiplier=1.0,
                volume_profile_bonus_multiplier=1.0,
                indicators={},
                modules={},
            )

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
        logger.info(f"   Max holding: {params.max_holding_minutes} min")
        logger.info(f"   Cooldown after loss: {params.cooldown_after_loss_minutes} min")
        logger.info("")
        logger.info("✨ Profit Harvesting (adaptive):")
        logger.info(f"   Enabled: {'YES' if params.ph_enabled else 'NO'}")
        logger.info(f"   Threshold: ${params.ph_threshold:.2f}")
        logger.info(
            f"   Time Limit: {params.ph_time_limit}s ({params.ph_time_limit/60:.1f} min)"
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
                time_distribution[regime.value] = td.total_seconds() / total_time * 100

        return {
            "current_regime": self.current_regime.value,
            "time_in_current_regime": str(datetime.utcnow() - self.regime_start_time),
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
