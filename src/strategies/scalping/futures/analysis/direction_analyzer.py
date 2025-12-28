"""
Direction Analyzer - Анализатор направления рынка с взвешенной системой индикаторов.

Обеспечивает единое определение направления рынка на основе:
- ADX (наибольший вес)
- Moving Averages (EMA, SMA)
- Price action
- Volume analysis
- Trend deviation

Предотвращает конфликты между различными индикаторами и обеспечивает консистентность.
"""

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.models import OHLCV


class DirectionAnalyzer:
    """
    Анализатор направления рынка с взвешенной системой индикаторов.

    Объединяет сигналы от различных индикаторов для определения единого направления.
    """

    # Веса индикаторов для определения направления
    # Большее число = большее влияние
    INDICATOR_WEIGHTS = {
        "adx": 0.40,  # ADX - самый важный индикатор (40%)
        "ema": 0.25,  # EMA - важный индикатор (25%)
        "sma": 0.15,  # SMA - средний вес (15%)
        "price_action": 0.10,  # Price action (10%)
        "volume": 0.10,  # Volume analysis (10%)
    }

    # Пороги для определения направления
    ADX_STRONG_THRESHOLD = 25.0  # ADX >= 25 = сильный тренд
    ADX_MODERATE_THRESHOLD = 18.0  # ADX >= 18 = умеренный тренд
    DI_DIFFERENCE_THRESHOLD = 3.0  # Разница между +DI и -DI для определения направления

    def __init__(self, fast_adx=None, indicator_calculator=None):
        """
        Инициализация Direction Analyzer.

        Args:
            fast_adx: FastADX для расчета ADX (опционально)
            indicator_calculator: IndicatorCalculator для расчета индикаторов (опционально)
        """
        self.fast_adx = fast_adx
        self.indicator_calculator = indicator_calculator

        logger.info("✅ DirectionAnalyzer инициализирован")

    def analyze_direction(
        self,
        candles: List[OHLCV],
        current_price: float,
        indicators: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Анализирует направление рынка на основе взвешенной системы индикаторов.

        Args:
            candles: Список свечей
            current_price: Текущая цена
            indicators: Предрассчитанные индикаторы (опционально)

        Returns:
            Словарь с результатами анализа:
            {
                "direction": "bullish" | "bearish" | "neutral",
                "confidence": 0.0-1.0,
                "adx_value": float,
                "adx_direction": str,
                "ema_direction": str,
                "sma_direction": str,
                "price_action_direction": str,
                "volume_signal": str,
                "weighted_score": float,
                "reason": str
            }
        """
        try:
            if not candles or len(candles) < 20:
                return {
                    "direction": "neutral",
                    "confidence": 0.0,
                    "reason": "Недостаточно данных для анализа",
                }

            # 1. ADX анализ (вес 40%)
            adx_result = self._analyze_adx_direction(candles, indicators)
            adx_direction = adx_result["direction"]
            adx_value = adx_result["adx_value"]
            adx_confidence = adx_result["confidence"]

            # 2. EMA анализ (вес 25%)
            ema_result = self._analyze_ema_direction(candles, current_price, indicators)
            ema_direction = ema_result["direction"]
            ema_confidence = ema_result["confidence"]

            # 3. SMA анализ (вес 15%)
            sma_result = self._analyze_sma_direction(candles, current_price, indicators)
            sma_direction = sma_result["direction"]
            sma_confidence = sma_result["confidence"]

            # 4. Price Action анализ (вес 10%)
            price_action_result = self._analyze_price_action(candles, current_price)
            price_action_direction = price_action_result["direction"]
            price_action_confidence = price_action_result["confidence"]

            # 5. Volume анализ (вес 10%)
            volume_result = self._analyze_volume(candles)
            volume_signal = volume_result["signal"]
            volume_confidence = volume_result["confidence"]

            # Взвешенный расчет направления
            bullish_score = 0.0
            bearish_score = 0.0

            # ADX (40%)
            if adx_direction == "bullish":
                bullish_score += adx_confidence * self.INDICATOR_WEIGHTS["adx"]
            elif adx_direction == "bearish":
                bearish_score += adx_confidence * self.INDICATOR_WEIGHTS["adx"]

            # EMA (25%)
            if ema_direction == "bullish":
                bullish_score += ema_confidence * self.INDICATOR_WEIGHTS["ema"]
            elif ema_direction == "bearish":
                bearish_score += ema_confidence * self.INDICATOR_WEIGHTS["ema"]

            # SMA (15%)
            if sma_direction == "bullish":
                bullish_score += sma_confidence * self.INDICATOR_WEIGHTS["sma"]
            elif sma_direction == "bearish":
                bearish_score += sma_confidence * self.INDICATOR_WEIGHTS["sma"]

            # Price Action (10%)
            if price_action_direction == "bullish":
                bullish_score += (
                    price_action_confidence * self.INDICATOR_WEIGHTS["price_action"]
                )
            elif price_action_direction == "bearish":
                bearish_score += (
                    price_action_confidence * self.INDICATOR_WEIGHTS["price_action"]
                )

            # Volume (10%)
            if volume_signal == "bullish":
                bullish_score += volume_confidence * self.INDICATOR_WEIGHTS["volume"]
            elif volume_signal == "bearish":
                bearish_score += volume_confidence * self.INDICATOR_WEIGHTS["volume"]

            # Определяем финальное направление
            if bullish_score > bearish_score and bullish_score > 0.5:
                direction = "bullish"
                confidence = min(1.0, bullish_score)
                reason = f"Bullish: ADX={adx_direction}, EMA={ema_direction}, SMA={sma_direction}, PA={price_action_direction}, Vol={volume_signal}"
            elif bearish_score > bullish_score and bearish_score > 0.5:
                direction = "bearish"
                confidence = min(1.0, bearish_score)
                reason = f"Bearish: ADX={adx_direction}, EMA={ema_direction}, SMA={sma_direction}, PA={price_action_direction}, Vol={volume_signal}"
            else:
                direction = "neutral"
                confidence = max(bullish_score, bearish_score)
                reason = f"Neutral: недостаточная уверенность (bullish={bullish_score:.2f}, bearish={bearish_score:.2f})"

            return {
                "direction": direction,
                "confidence": confidence,
                "adx_value": adx_value,
                "adx_direction": adx_direction,
                "ema_direction": ema_direction,
                "sma_direction": sma_direction,
                "price_action_direction": price_action_direction,
                "volume_signal": volume_signal,
                "weighted_score": max(bullish_score, bearish_score),
                "bullish_score": bullish_score,
                "bearish_score": bearish_score,
                "reason": reason,
            }

        except Exception as e:
            logger.error(
                f"❌ DirectionAnalyzer: Ошибка анализа направления: {e}",
                exc_info=True,
            )
            return {
                "direction": "neutral",
                "confidence": 0.0,
                "reason": f"Ошибка анализа: {e}",
            }

    def _analyze_adx_direction(
        self, candles: List[OHLCV], indicators: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Анализирует направление на основе ADX.

        Returns:
            {"direction": str, "adx_value": float, "confidence": float}
        """
        try:
            adx_value = 0.0
            di_plus = 0.0
            di_minus = 0.0

            # Получаем ADX из индикаторов или рассчитываем
            if indicators:
                adx_value = indicators.get("adx", 0.0) or indicators.get(
                    "adx_proxy", 0.0
                )
                di_plus = indicators.get("di_plus", 0.0)
                di_minus = indicators.get("di_minus", 0.0)
            elif self.fast_adx:
                # Обновляем FastADX с историческими данными
                for candle in candles[-self.fast_adx.period :]:
                    self.fast_adx.update(
                        high=candle.high, low=candle.low, close=candle.close
                    )
                adx_value = self.fast_adx.get_adx_value()
                di_plus = self.fast_adx.get_di_plus()
                di_minus = self.fast_adx.get_di_minus()

            if adx_value < self.ADX_MODERATE_THRESHOLD:
                return {
                    "direction": "neutral",
                    "adx_value": adx_value,
                    "confidence": 0.0,
                }

            # Определяем направление по разнице DI
            di_difference = di_plus - di_minus

            if di_difference > self.DI_DIFFERENCE_THRESHOLD:
                direction = "bullish"
                # Confidence зависит от силы ADX и разницы DI
                confidence = min(
                    1.0,
                    (adx_value / 50.0) * 0.7 + (abs(di_difference) / 10.0) * 0.3,
                )
            elif di_difference < -self.DI_DIFFERENCE_THRESHOLD:
                direction = "bearish"
                confidence = min(
                    1.0,
                    (adx_value / 50.0) * 0.7 + (abs(di_difference) / 10.0) * 0.3,
                )
            else:
                direction = "neutral"
                confidence = 0.3  # Слабая уверенность при близких DI

            return {
                "direction": direction,
                "adx_value": adx_value,
                "confidence": confidence,
            }

        except Exception as e:
            logger.debug(f"⚠️ DirectionAnalyzer: Ошибка ADX анализа: {e}")
            return {"direction": "neutral", "adx_value": 0.0, "confidence": 0.0}

    def _analyze_ema_direction(
        self,
        candles: List[OHLCV],
        current_price: float,
        indicators: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Анализирует направление на основе EMA.

        Returns:
            {"direction": str, "confidence": float}
        """
        try:
            ema_fast = None
            ema_slow = None

            if indicators:
                ema_fast = indicators.get("ema_fast") or indicators.get("ema_12")
                ema_slow = indicators.get("ema_slow") or indicators.get("ema_26")
            elif self.indicator_calculator:
                ema_fast = self.indicator_calculator.calculate_ema(candles, period=12)
                ema_slow = self.indicator_calculator.calculate_ema(candles, period=26)

            if not ema_fast or not ema_slow or ema_slow == 0:
                return {"direction": "neutral", "confidence": 0.0}

            # Определяем направление
            if ema_fast > ema_slow and current_price > ema_fast:
                direction = "bullish"
                # Confidence зависит от разницы EMA и позиции цены
                ema_diff_pct = ((ema_fast - ema_slow) / ema_slow) * 100
                price_above_pct = ((current_price - ema_fast) / ema_fast) * 100
                confidence = min(
                    1.0, (ema_diff_pct / 2.0) * 0.5 + (price_above_pct / 1.0) * 0.5
                )
            elif ema_fast < ema_slow and current_price < ema_fast:
                direction = "bearish"
                ema_diff_pct = ((ema_slow - ema_fast) / ema_fast) * 100
                price_below_pct = ((ema_fast - current_price) / ema_fast) * 100
                confidence = min(
                    1.0, (ema_diff_pct / 2.0) * 0.5 + (price_below_pct / 1.0) * 0.5
                )
            else:
                direction = "neutral"
                confidence = 0.3

            return {"direction": direction, "confidence": confidence}

        except Exception as e:
            logger.debug(f"⚠️ DirectionAnalyzer: Ошибка EMA анализа: {e}")
            return {"direction": "neutral", "confidence": 0.0}

    def _analyze_sma_direction(
        self,
        candles: List[OHLCV],
        current_price: float,
        indicators: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Анализирует направление на основе SMA.

        Returns:
            {"direction": str, "confidence": float}
        """
        try:
            sma = None

            if indicators:
                sma = indicators.get("sma") or indicators.get("sma_20")
            elif self.indicator_calculator:
                sma = self.indicator_calculator.calculate_sma(candles, period=20)

            if not sma or sma == 0:
                return {"direction": "neutral", "confidence": 0.0}

            # Определяем направление по позиции цены относительно SMA
            price_diff_pct = ((current_price - sma) / sma) * 100

            if price_diff_pct > 1.0:  # Цена >1% выше SMA
                direction = "bullish"
                confidence = min(1.0, price_diff_pct / 5.0)
            elif price_diff_pct < -1.0:  # Цена >1% ниже SMA
                direction = "bearish"
                confidence = min(1.0, abs(price_diff_pct) / 5.0)
            else:
                direction = "neutral"
                confidence = 0.3

            return {"direction": direction, "confidence": confidence}

        except Exception as e:
            logger.debug(f"⚠️ DirectionAnalyzer: Ошибка SMA анализа: {e}")
            return {"direction": "neutral", "confidence": 0.0}

    def _analyze_price_action(
        self, candles: List[OHLCV], current_price: float
    ) -> Dict[str, Any]:
        """
        Анализирует направление на основе Price Action.

        Returns:
            {"direction": str, "confidence": float}
        """
        try:
            if len(candles) < 5:
                return {"direction": "neutral", "confidence": 0.0}

            # Анализируем последние 5 свечей
            recent_candles = candles[-5:]
            closes = [c.close for c in recent_candles]
            highs = [c.high for c in recent_candles]
            lows = [c.low for c in recent_candles]

            # Подсчитываем бычьи и медвежьи свечи
            bullish_candles = sum(
                1 for i in range(1, len(closes)) if closes[i] > closes[i - 1]
            )
            bearish_candles = sum(
                1 for i in range(1, len(closes)) if closes[i] < closes[i - 1]
            )

            # Анализируем высшие максимумы и низшие минимумы
            higher_highs = sum(
                1 for i in range(1, len(highs)) if highs[i] > highs[i - 1]
            )
            lower_lows = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])

            # Определяем направление
            if bullish_candles >= 3 and higher_highs >= 2:
                direction = "bullish"
                confidence = min(
                    1.0, (bullish_candles / 5.0) * 0.7 + (higher_highs / 4.0) * 0.3
                )
            elif bearish_candles >= 3 and lower_lows >= 2:
                direction = "bearish"
                confidence = min(
                    1.0, (bearish_candles / 5.0) * 0.7 + (lower_lows / 4.0) * 0.3
                )
            else:
                direction = "neutral"
                confidence = 0.3

            return {"direction": direction, "confidence": confidence}

        except Exception as e:
            logger.debug(f"⚠️ DirectionAnalyzer: Ошибка Price Action анализа: {e}")
            return {"direction": "neutral", "confidence": 0.0}

    def _analyze_volume(self, candles: List[OHLCV]) -> Dict[str, Any]:
        """
        Анализирует направление на основе Volume.

        Returns:
            {"signal": str, "confidence": float}
        """
        try:
            if len(candles) < 20:
                return {"signal": "neutral", "confidence": 0.0}

            volumes = [c.volume for c in candles]
            closes = [c.close for c in candles]

            # Средний объем
            avg_volume = sum(volumes[-20:]) / 20
            current_volume = volumes[-1]

            # Объемный анализ
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

            # Анализируем объем при росте/падении цены
            price_changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
            recent_changes = price_changes[-5:]
            recent_volumes = volumes[-5:]

            bullish_volume = sum(
                vol for change, vol in zip(recent_changes, recent_volumes) if change > 0
            )
            bearish_volume = sum(
                vol for change, vol in zip(recent_changes, recent_volumes) if change < 0
            )

            total_volume = bullish_volume + bearish_volume
            if total_volume == 0:
                return {"signal": "neutral", "confidence": 0.0}

            bullish_ratio = bullish_volume / total_volume
            bearish_ratio = bearish_volume / total_volume

            # Определяем сигнал
            if volume_ratio > 1.2 and bullish_ratio > 0.6:
                signal = "bullish"
                confidence = min(1.0, (volume_ratio - 1.0) * 0.5 + bullish_ratio * 0.5)
            elif volume_ratio > 1.2 and bearish_ratio > 0.6:
                signal = "bearish"
                confidence = min(1.0, (volume_ratio - 1.0) * 0.5 + bearish_ratio * 0.5)
            else:
                signal = "neutral"
                confidence = 0.3

            return {"signal": signal, "confidence": confidence}

        except Exception as e:
            logger.debug(f"⚠️ DirectionAnalyzer: Ошибка Volume анализа: {e}")
            return {"signal": "neutral", "confidence": 0.0}

    def get_weights(self) -> Dict[str, float]:
        """
        Получить веса индикаторов для отладки.

        Returns:
            Словарь {индикатор: вес}
        """
        return self.INDICATOR_WEIGHTS.copy()
