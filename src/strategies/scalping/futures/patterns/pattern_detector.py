"""
Pattern Detector Module for Trading Bot
Определение технических паттернов для генерации сигналов
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class PatternType(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class PatternStrength(Enum):
    STRONG = 3
    MEDIUM = 2
    WEAK = 1


@dataclass
class PatternSignal:
    """Структура для сигнала паттерна"""

    pattern_name: str
    pattern_type: PatternType
    strength: PatternStrength
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float  # 0.0 - 1.0
    timestamp: pd.Timestamp
    timeframe: str


class PatternDetector:
    """Детектор технических паттернов"""

    def __init__(self):
        self.min_bars_for_pattern = 3
        self.pinbar_threshold = 0.7  # 70% тени должно быть с одной стороны
        self.engulfing_min_ratio = 1.2  # Минимальное поглощение

    def detect_patterns(
        self,
        df: pd.DataFrame,
        support_levels: List[float] = None,
        resistance_levels: List[float] = None,
    ) -> List[PatternSignal]:
        """
        Основной метод обнаружения всех паттернов

        Args:
            df: DataFrame с OHLCV данными
            support_levels: Список уровней поддержки
            resistance_levels: Список уровней сопротивления

        Returns:
            Список найденных паттернов
        """
        signals = []

        # Детектируем каждый паттерн
        signals.extend(self.detect_pinbar(df, support_levels, resistance_levels))
        signals.extend(self.detect_engulfing(df))
        signals.extend(self.detect_inside_bar(df))
        signals.extend(
            self.detect_breakout_retest(df, support_levels, resistance_levels)
        )
        signals.extend(self.detect_fakey(df))
        signals.extend(self.detect_three_candles(df))

        # Сортируем по силе и времени
        signals.sort(key=lambda x: (x.strength.value, x.confidence), reverse=True)

        return signals

    def detect_pinbar(
        self,
        df: pd.DataFrame,
        support_levels: List[float] = None,
        resistance_levels: List[float] = None,
    ) -> List[PatternSignal]:
        """
        Детектирует пинбары (молот, shooting star, hanging man)

        Пинбар = длинная тень + маленькое тело + короткая противоположная тень
        """
        signals = []

        for i in range(2, len(df)):
            current = df.iloc[i]

            # Расчет параметров свечи
            body_size = abs(current["close"] - current["open"])
            total_size = current["high"] - current["low"]
            upper_shadow = current["high"] - max(current["open"], current["close"])
            lower_shadow = min(current["open"], current["close"]) - current["low"]

            if total_size == 0:
                continue

            # Проверка на пинбар
            body_ratio = body_size / total_size
            upper_ratio = upper_shadow / total_size
            lower_ratio = lower_shadow / total_size

            # Пинбар должен иметь маленькое тело и длинную тень
            if body_ratio > 0.3:  # Тело больше 30% - не пинбар
                continue

            # Определяем тип пинбара
            is_bullish_pinbar = (
                lower_ratio > self.pinbar_threshold
                and upper_ratio < 0.15
                and current["close"] > current["open"]
            )

            is_bearish_pinbar = (
                upper_ratio > self.pinbar_threshold
                and lower_ratio < 0.15
                and current["close"] < current["open"]
            )

            # Проверяем совпадение с уровнями S/R
            near_support = False
            near_resistance = False

            if support_levels:
                near_support = any(
                    abs(current["low"] - level) / level < 0.005
                    for level in support_levels
                )

            if resistance_levels:
                near_resistance = any(
                    abs(current["high"] - level) / level < 0.005
                    for level in resistance_levels
                )

            # Генерируем сигнал
            if is_bullish_pinbar and near_support:
                signal = PatternSignal(
                    pattern_name="Bullish Pinbar at Support",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.STRONG
                    if near_support
                    else PatternStrength.MEDIUM,
                    entry_price=current["close"],
                    stop_loss=current["low"] * 0.998,  # Ниже хвоста
                    take_profit=current["close"]
                    + (current["close"] - current["low"]) * 2,
                    confidence=0.85 if near_support else 0.7,
                    timestamp=df.index[i],
                    timeframe="15m",
                )
                signals.append(signal)

            elif is_bearish_pinbar and near_resistance:
                signal = PatternSignal(
                    pattern_name="Bearish Pinbar at Resistance",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.STRONG
                    if near_resistance
                    else PatternStrength.MEDIUM,
                    entry_price=current["close"],
                    stop_loss=current["high"] * 1.002,  # Выше хвоста
                    take_profit=current["close"]
                    - (current["high"] - current["close"]) * 2,
                    confidence=0.85 if near_resistance else 0.7,
                    timestamp=df.index[i],
                    timeframe="15m",
                )
                signals.append(signal)

        return signals

    def detect_engulfing(self, df: pd.DataFrame) -> List[PatternSignal]:
        """
        Детектирует поглощающие паттерны (bullish/bearish engulfing)

        Bullish: зеленая свеча полностью поглощает предыдущую красную
        Bearish: красная свеча полностью поглощает предыдущую зеленую
        """
        signals = []

        for i in range(1, len(df)):
            current = df.iloc[i]
            previous = df.iloc[i - 1]

            # Bullish Engulfing
            if (
                previous["close"] < previous["open"]
                and current["close"] > current["open"]  # Предыдущая красная
                and current["open"] < previous["close"]  # Текущая зеленая
                and current["close"]  # Открытие ниже предыдущего close
                > previous["open"]
            ):  # Close выше предыдущего open
                body_ratio = abs(current["close"] - current["open"]) / abs(
                    previous["close"] - previous["open"]
                )

                if body_ratio > self.engulfing_min_ratio:
                    signal = PatternSignal(
                        pattern_name="Bullish Engulfing",
                        pattern_type=PatternType.BULLISH,
                        strength=PatternStrength.MEDIUM,
                        entry_price=current["close"],
                        stop_loss=current["low"] * 0.998,
                        take_profit=current["close"]
                        + abs(current["close"] - current["open"]) * 2,
                        confidence=min(0.75, body_ratio * 0.5),
                        timestamp=df.index[i],
                        timeframe="15m",
                    )
                    signals.append(signal)

            # Bearish Engulfing
            elif (
                previous["close"] > previous["open"]
                and current["close"] < current["open"]  # Предыдущая зеленая
                and current["open"] > previous["close"]  # Текущая красная
                and current["close"]  # Открытие выше предыдущего close
                < previous["open"]
            ):  # Close ниже предыдущего open
                body_ratio = abs(current["close"] - current["open"]) / abs(
                    previous["close"] - previous["open"]
                )

                if body_ratio > self.engulfing_min_ratio:
                    signal = PatternSignal(
                        pattern_name="Bearish Engulfing",
                        pattern_type=PatternType.BEARISH,
                        strength=PatternStrength.MEDIUM,
                        entry_price=current["close"],
                        stop_loss=current["high"] * 1.002,
                        take_profit=current["close"]
                        - abs(current["close"] - current["open"]) * 2,
                        confidence=min(0.75, body_ratio * 0.5),
                        timestamp=df.index[i],
                        timeframe="15m",
                    )
                    signals.append(signal)

        return signals

    def detect_inside_bar(self, df: pd.DataFrame) -> List[PatternSignal]:
        """
        Детектирует внутренние свечи (Inside Bar)

        Inside Bar: текущая свеча полностью внутри предыдущей
        """
        signals = []

        for i in range(1, len(df)):
            current = df.iloc[i]
            previous = df.iloc[i - 1]

            # Inside Bar: High текущей < High предыдущей, Low текущей > Low предыдущей
            if current["high"] < previous["high"] and current["low"] > previous["low"]:
                # Ждем прорыва на следующей свече
                if i + 1 < len(df):
                    next_candle = df.iloc[i + 1]

                    # Bullish breakout
                    if next_candle["close"] > previous["high"]:
                        signal = PatternSignal(
                            pattern_name="Inside Bar Bullish Breakout",
                            pattern_type=PatternType.BULLISH,
                            strength=PatternStrength.MEDIUM,
                            entry_price=next_candle["close"],
                            stop_loss=current["low"] * 0.998,
                            take_profit=next_candle["close"]
                            + (previous["high"] - current["low"]) * 1.5,
                            confidence=0.7,
                            timestamp=df.index[i + 1],
                            timeframe="15m",
                        )
                        signals.append(signal)

                    # Bearish breakout
                    elif next_candle["close"] < previous["low"]:
                        signal = PatternSignal(
                            pattern_name="Inside Bar Bearish Breakout",
                            pattern_type=PatternType.BEARISH,
                            strength=PatternStrength.MEDIUM,
                            entry_price=next_candle["close"],
                            stop_loss=current["high"] * 1.002,
                            take_profit=next_candle["close"]
                            - (current["high"] - previous["low"]) * 1.5,
                            confidence=0.7,
                            timestamp=df.index[i + 1],
                            timeframe="15m",
                        )
                        signals.append(signal)

        return signals

    def detect_breakout_retest(
        self,
        df: pd.DataFrame,
        support_levels: List[float] = None,
        resistance_levels: List[float] = None,
    ) -> List[PatternSignal]:
        """
        Детектирует прорыв с ретестом уровня

        Сначала прорыв уровня, затем откат к уровню и отбой
        """
        signals = []

        if not support_levels and not resistance_levels:
            return signals

        all_levels = (support_levels or []) + (resistance_levels or [])

        for level in all_levels:
            # Ищем прорыв уровня
            breakout_idx = None
            breakout_direction = None

            for i in range(5, len(df) - 5):  # Оставляем место для ретеста
                current = df.iloc[i]
                prev_candles = df.iloc[i - 5 : i]
                next_candles = df.iloc[i + 1 : i + 6]

                # Проверяем прорыв сопротивления
                if current["high"] > level and all(
                    candle["high"] < level for candle in prev_candles.itertuples()
                ):
                    # Ищем ретест (откат к уровню)
                    for j in range(i + 1, min(i + 6, len(df))):
                        retest_candle = df.iloc[j]

                        # Ретест: цена откатывает к уровню и отбивается
                        if (
                            abs(retest_candle["low"] - level) / level < 0.003
                            and retest_candle["close"] > level
                        ):
                            signal = PatternSignal(
                                pattern_name="Breakout + Retest (Resistance)",
                                pattern_type=PatternType.BULLISH,
                                strength=PatternStrength.STRONG,
                                entry_price=retest_candle["close"],
                                stop_loss=level * 0.995,
                                take_profit=level + (level - retest_candle["low"]) * 2,
                                confidence=0.8,
                                timestamp=df.index[j],
                                timeframe="15m",
                            )
                            signals.append(signal)
                            break

                # Проверяем прорыв поддержки
                elif current["low"] < level and all(
                    candle["low"] > level for candle in prev_candles.itertuples()
                ):
                    # Ищем ретест (откат к уровню)
                    for j in range(i + 1, min(i + 6, len(df))):
                        retest_candle = df.iloc[j]

                        # Ретест: цена откатывает к уровню и отбивается
                        if (
                            abs(retest_candle["high"] - level) / level < 0.003
                            and retest_candle["close"] < level
                        ):
                            signal = PatternSignal(
                                pattern_name="Breakdown + Retest (Support)",
                                pattern_type=PatternType.BEARISH,
                                strength=PatternStrength.STRONG,
                                entry_price=retest_candle["close"],
                                stop_loss=level * 1.005,
                                take_profit=level - (retest_candle["high"] - level) * 2,
                                confidence=0.8,
                                timestamp=df.index[j],
                                timeframe="15m",
                            )
                            signals.append(signal)
                            break

        return signals

    def detect_fakey(self, df: pd.DataFrame) -> List[PatternSignal]:
        """
        Детектирует Fakey (ложный прорыв) - паттерн ловушки

        Внутренняя свеча + ложный прорыв + возврат внутрь
        """
        signals = []

        for i in range(2, len(df)):
            current = df.iloc[i]
            prev1 = df.iloc[i - 1]  # Внутренняя свеча
            prev2 = df.iloc[i - 2]  # Материнская свеча

            # Проверяем Inside Bar (prev1 внутри prev2)
            if not (prev1["high"] < prev2["high"] and prev1["low"] > prev2["low"]):
                continue

            # Проверяем ложный прорыв текущей свечой
            # Сначала прорыв за пределы материнской свечи
            # Затем возврат внутрь

            # Bullish Fakey: ложный пробой вниз + возврат
            if (
                current["low"] < prev2["low"]
                and current["close"] > prev1["high"]  # Пробой ниже материнской
            ):  # Возврат выше внутренней
                signal = PatternSignal(
                    pattern_name="Bullish Fakey",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.STRONG,
                    entry_price=current["close"],
                    stop_loss=current["low"] * 0.998,
                    take_profit=current["close"] + (prev2["high"] - current["low"]) * 2,
                    confidence=0.8,
                    timestamp=df.index[i],
                    timeframe="15m",
                )
                signals.append(signal)

            # Bearish Fakey: ложный пробой вверх + возврат
            elif (
                current["high"] > prev2["high"]
                and current["close"] < prev1["low"]  # Пробой выше материнской
            ):  # Возврат ниже внутренней
                signal = PatternSignal(
                    pattern_name="Bearish Fakey",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.STRONG,
                    entry_price=current["close"],
                    stop_loss=current["high"] * 1.002,
                    take_profit=current["close"] - (current["high"] - prev2["low"]) * 2,
                    confidence=0.8,
                    timestamp=df.index[i],
                    timeframe="15m",
                )
                signals.append(signal)

        return signals

    def detect_three_candles(self, df: pd.DataFrame) -> List[PatternSignal]:
        """
        Детектирует паттерн трех одинаковых свечей (Three Soldiers / Three Crows)

        Three Soldiers: три подряд растущие свечи с увеличивающимися телами
        Three Crows: три подряд падающие свечи с увеличивающимися телами
        """
        signals = []

        for i in range(2, len(df)):
            c1, c2, c3 = df.iloc[i - 2], df.iloc[i - 1], df.iloc[i]

            # Three White Soldiers
            if (
                c1["close"] > c1["open"]
                and c2["close"] > c2["open"]  # Первая зеленая
                and c3["close"] > c3["open"]  # Вторая зеленая
                and c1["close"] < c2["open"]  # Третья зеленая
                and c2["close"] < c3["open"]  # Переход между свечами
                and abs(c3["close"] - c3["open"])
                > abs(c2["close"] - c2["open"])
                > abs(c1["close"] - c1["open"])
            ):
                signal = PatternSignal(
                    pattern_name="Three White Soldiers",
                    pattern_type=PatternType.BULLISH,
                    strength=PatternStrength.MEDIUM,
                    entry_price=c3["close"],
                    stop_loss=c1["low"] * 0.998,
                    take_profit=c3["close"] + (c3["close"] - c1["low"]) * 1.5,
                    confidence=0.75,
                    timestamp=df.index[i],
                    timeframe="15m",
                )
                signals.append(signal)

            # Three Black Crows
            elif (
                c1["close"] < c1["open"]
                and c2["close"] < c2["open"]  # Первая красная
                and c3["close"] < c3["open"]  # Вторая красная
                and c1["close"] > c2["open"]  # Третья красная
                and c2["close"] > c3["open"]  # Переход между свечами
                and abs(c3["close"] - c3["open"])
                > abs(c2["close"] - c2["open"])
                > abs(c1["close"] - c1["open"])
            ):
                signal = PatternSignal(
                    pattern_name="Three Black Crows",
                    pattern_type=PatternType.BEARISH,
                    strength=PatternStrength.MEDIUM,
                    entry_price=c3["close"],
                    stop_loss=c1["high"] * 1.002,
                    take_profit=c3["close"] - (c1["high"] - c3["close"]) * 1.5,
                    confidence=0.75,
                    timestamp=df.index[i],
                    timeframe="15m",
                )
                signals.append(signal)

        return signals


# Пример использования
if __name__ == "__main__":
    # Создаем пример данных
    dates = pd.date_range("2024-01-01", periods=100, freq="15min")
    np.random.seed(42)

    # Генерируем пример OHLC данных
    base_price = 50000
    noise = np.random.randn(100) * 100

    df = pd.DataFrame(
        {
            "open": base_price + np.cumsum(noise * 0.1),
            "high": base_price
            + np.cumsum(noise * 0.1)
            + np.abs(np.random.randn(100) * 50),
            "low": base_price
            + np.cumsum(noise * 0.1)
            - np.abs(np.random.randn(100) * 50),
            "close": base_price + np.cumsum(noise * 0.1) + np.random.randn(100) * 20,
            "volume": np.random.randint(1000, 10000, 100),
        },
        index=dates,
    )

    # Корректируем high/low
    df["high"] = df[["open", "close", "high"]].max(axis=1)
    df["low"] = df[["open", "close", "low"]].min(axis=1)

    # Инициализируем детектор
    detector = PatternDetector()

    # Уровни поддержки и сопротивления
    support_levels = [49500, 49200]
    resistance_levels = [50500, 50800]

    # Детектируем паттерны
    signals = detector.detect_patterns(df, support_levels, resistance_levels)

    print(f"Найдено паттернов: {len(signals)}")
    for signal in signals[:5]:  # Показываем первые 5
        print(f"\n{signal.pattern_name} | {signal.pattern_type.value}")
        print(f"   Цена входа: {signal.entry_price:.2f}")
        print(f"   Stop Loss: {signal.stop_loss:.2f}")
        print(f"   Take Profit: {signal.take_profit:.2f}")
        print(f"   Уверенность: {signal.confidence:.2%}")
