from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PatternSignal:
    name: str
    bias: int  # 1 bullish, -1 bearish
    strength: float  # 0..1
    confidence: float  # 0..1
    entry: float
    stop: float
    target: float


class PatternEngine:
    """
    Lightweight pattern engine operating on OHLCV candles.
    No external dependencies, deterministic, ASCII-only.
    """

    def evaluate(
        self,
        candles: List[Any],
        current_price: float,
        pattern_params: Any,
    ) -> Dict[str, Any]:
        thresholds = getattr(pattern_params, "thresholds", {}) or {}
        required = (
            "min_confidence",
            "min_strength",
            "boost_multiplier",
            "penalty_multiplier",
            "breakout_pct",
            "pinbar_wick_ratio",
            "min_bars",
        )
        missing = [key for key in required if key not in thresholds]
        if missing:
            return {
                "valid": False,
                "errors": [f"pattern_thresholds_missing: {', '.join(missing)}"],
                "bias": 0,
                "confidence": 0.0,
                "signals": [],
                "min_confidence": 0.0,
                "min_strength": 0.0,
                "boost_multiplier": 0.0,
                "penalty_multiplier": 0.0,
            }

        min_confidence = float(thresholds["min_confidence"])
        min_strength = float(thresholds["min_strength"])
        boost_multiplier = float(thresholds["boost_multiplier"])
        penalty_multiplier = float(thresholds["penalty_multiplier"])
        breakout_pct = float(thresholds["breakout_pct"])
        pinbar_wick_ratio = float(thresholds["pinbar_wick_ratio"])
        min_bars = int(thresholds["min_bars"])

        if not candles or len(candles) < max(5, min_bars):
            return {
                "valid": False,
                "errors": ["insufficient_candles_for_patterns"],
                "bias": 0,
                "confidence": 0.0,
                "signals": [],
                "min_confidence": min_confidence,
                "min_strength": min_strength,
                "boost_multiplier": boost_multiplier,
                "penalty_multiplier": penalty_multiplier,
            }

        signals: List[PatternSignal] = []
        signals += self._detect_pinbar(candles, pinbar_wick_ratio)
        signals += self._detect_engulfing(candles)
        signals += self._detect_inside_bar(candles)
        signals += self._detect_three_candles(candles)
        signals += self._detect_breakout(candles, breakout_pct)

        bullish_score = 0.0
        bearish_score = 0.0
        for sig in signals:
            score = sig.strength * sig.confidence
            if sig.bias > 0:
                bullish_score += score
            elif sig.bias < 0:
                bearish_score += score

        total = bullish_score + bearish_score
        delta = bullish_score - bearish_score
        bias = 1 if delta > 0 else -1 if delta < 0 else 0
        confidence = abs(delta) / total if total > 0 else 0.0

        return {
            "valid": True,
            "errors": [],
            "bias": bias,
            "confidence": confidence,
            "signals": signals,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
            "min_confidence": min_confidence,
            "min_strength": min_strength,
            "boost_multiplier": boost_multiplier,
            "penalty_multiplier": penalty_multiplier,
        }

    @staticmethod
    def _extract(candle: Any) -> Tuple[float, float, float, float]:
        if isinstance(candle, dict):
            return (
                float(candle.get("open", 0.0)),
                float(candle.get("high", 0.0)),
                float(candle.get("low", 0.0)),
                float(candle.get("close", 0.0)),
            )
        return (
            float(getattr(candle, "open", 0.0)),
            float(getattr(candle, "high", 0.0)),
            float(getattr(candle, "low", 0.0)),
            float(getattr(candle, "close", 0.0)),
        )

    def _detect_pinbar(
        self, candles: List[Any], wick_ratio: float
    ) -> List[PatternSignal]:
        signals: List[PatternSignal] = []
        if len(candles) < 2:
            return signals
        o, h, l, c = self._extract(candles[-1])
        total = max(h - l, 1e-9)
        body = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        if body / total > 0.35:
            return signals
        upper_ratio = upper / total
        lower_ratio = lower / total
        if lower_ratio >= wick_ratio and upper_ratio <= 0.2:
            signals.append(
                PatternSignal(
                    name="pinbar_bullish",
                    bias=1,
                    strength=min(1.0, lower_ratio),
                    confidence=min(1.0, lower_ratio),
                    entry=c,
                    stop=l * 0.999,
                    target=c + (c - l) * 2.0,
                )
            )
        if upper_ratio >= wick_ratio and lower_ratio <= 0.2:
            signals.append(
                PatternSignal(
                    name="pinbar_bearish",
                    bias=-1,
                    strength=min(1.0, upper_ratio),
                    confidence=min(1.0, upper_ratio),
                    entry=c,
                    stop=h * 1.001,
                    target=c - (h - c) * 2.0,
                )
            )
        return signals

    def _detect_engulfing(self, candles: List[Any]) -> List[PatternSignal]:
        signals: List[PatternSignal] = []
        if len(candles) < 2:
            return signals
        o1, h1, l1, c1 = self._extract(candles[-2])
        o2, h2, l2, c2 = self._extract(candles[-1])
        prev_red = c1 < o1
        prev_green = c1 > o1
        curr_green = c2 > o2
        curr_red = c2 < o2
        if prev_red and curr_green and o2 <= c1 and c2 >= o1:
            strength = min(1.0, abs(c2 - o2) / max(abs(c1 - o1), 1e-9))
            signals.append(
                PatternSignal(
                    name="engulfing_bullish",
                    bias=1,
                    strength=strength,
                    confidence=min(1.0, strength * 0.8),
                    entry=c2,
                    stop=min(l1, l2) * 0.999,
                    target=c2 + abs(c2 - o2) * 2.0,
                )
            )
        if prev_green and curr_red and o2 >= c1 and c2 <= o1:
            strength = min(1.0, abs(c2 - o2) / max(abs(c1 - o1), 1e-9))
            signals.append(
                PatternSignal(
                    name="engulfing_bearish",
                    bias=-1,
                    strength=strength,
                    confidence=min(1.0, strength * 0.8),
                    entry=c2,
                    stop=max(h1, h2) * 1.001,
                    target=c2 - abs(c2 - o2) * 2.0,
                )
            )
        return signals

    def _detect_inside_bar(self, candles: List[Any]) -> List[PatternSignal]:
        signals: List[PatternSignal] = []
        if len(candles) < 2:
            return signals
        o1, h1, l1, c1 = self._extract(candles[-2])
        o2, h2, l2, c2 = self._extract(candles[-1])
        if h2 < h1 and l2 > l1:
            bias = 1 if c2 > o2 else -1
            signals.append(
                PatternSignal(
                    name="inside_bar",
                    bias=bias,
                    strength=0.4,
                    confidence=0.5,
                    entry=c2,
                    stop=l2 * 0.999 if bias > 0 else h2 * 1.001,
                    target=c2 + (c2 - l2) if bias > 0 else c2 - (h2 - c2),
                )
            )
        return signals

    def _detect_three_candles(self, candles: List[Any]) -> List[PatternSignal]:
        signals: List[PatternSignal] = []
        if len(candles) < 3:
            return signals
        closes = [self._extract(c)[3] for c in candles[-3:]]
        if closes[0] < closes[1] < closes[2]:
            signals.append(
                PatternSignal(
                    name="three_candles_bullish",
                    bias=1,
                    strength=0.6,
                    confidence=0.6,
                    entry=closes[-1],
                    stop=closes[-1] * 0.995,
                    target=closes[-1] * 1.01,
                )
            )
        if closes[0] > closes[1] > closes[2]:
            signals.append(
                PatternSignal(
                    name="three_candles_bearish",
                    bias=-1,
                    strength=0.6,
                    confidence=0.6,
                    entry=closes[-1],
                    stop=closes[-1] * 1.005,
                    target=closes[-1] * 0.99,
                )
            )
        return signals

    def _detect_breakout(
        self, candles: List[Any], breakout_pct: float
    ) -> List[PatternSignal]:
        signals: List[PatternSignal] = []
        if len(candles) < 6:
            return signals
        recent = candles[-6:-1]
        highs = [self._extract(c)[1] for c in recent]
        lows = [self._extract(c)[2] for c in recent]
        last_o, last_h, last_l, last_c = self._extract(candles[-1])
        recent_high = max(highs)
        recent_low = min(lows)
        if recent_high > 0 and last_c > recent_high * (1 + breakout_pct):
            signals.append(
                PatternSignal(
                    name="breakout_bullish",
                    bias=1,
                    strength=0.7,
                    confidence=0.7,
                    entry=last_c,
                    stop=recent_high * 0.997,
                    target=last_c + (last_c - recent_high) * 2.0,
                )
            )
        if recent_low > 0 and last_c < recent_low * (1 - breakout_pct):
            signals.append(
                PatternSignal(
                    name="breakout_bearish",
                    bias=-1,
                    strength=0.7,
                    confidence=0.7,
                    entry=last_c,
                    stop=recent_low * 1.003,
                    target=last_c - (recent_low - last_c) * 2.0,
                )
            )
        return signals
