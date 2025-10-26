"""
Futures Signal Generator для скальпинг стратегии.

Основные функции:
- Генерация торговых сигналов для Futures
- Адаптация под Futures специфику (леверидж, маржа)
- Интеграция с техническими индикаторами
- Фильтрация сигналов по силе и качеству
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.config import BotConfig, ScalpingConfig
from src.indicators import IndicatorManager
from src.models import OHLCV, MarketData
from src.strategies.modules.adaptive_regime_manager import \
    AdaptiveRegimeManager
from src.strategies.modules.correlation_filter import CorrelationFilter
from src.strategies.modules.multi_timeframe import MultiTimeframeFilter
from src.strategies.modules.pivot_points import PivotPointsFilter
from src.strategies.modules.volume_profile_filter import VolumeProfileFilter


class FuturesSignalGenerator:
    """
    Генератор сигналов для Futures торговли

    Особенности:
    - Учет левериджа и маржи
    - Адаптация под Futures специфику
    - Интеграция с модулями фильтрации
    - Оптимизация для скальпинга
    """

    def __init__(self, config: BotConfig):
        """
        Инициализация Futures Signal Generator

        Args:
            config: Конфигурация бота
        """
        self.config = config
        self.scalping_config = config.scalping

        # Менеджер индикаторов
        from src.indicators import ATR, RSI, SimpleMovingAverage

        self.indicator_manager = IndicatorManager()
        # Добавляем базовые индикаторы
        self.indicator_manager.add_indicator(
            "RSI", RSI(period=14, overbought=70, oversold=30)
        )
        self.indicator_manager.add_indicator("ATR", ATR(period=14))
        self.indicator_manager.add_indicator("SMA", SimpleMovingAverage(period=20))

        # Модули фильтрации - ИНТЕГРАЦИЯ адаптивных систем
        self.regime_manager = None  # Инициализируется в initialize()
        self.correlation_filter = None
        self.mtf_filter = None
        self.pivot_filter = None
        self.volume_filter = None

        # Состояние
        self.is_initialized = False
        self.last_signals = {}
        self.signal_history = []

        logger.info("FuturesSignalGenerator инициализирован")

    async def initialize(self, ohlcv_data: Dict[str, List[OHLCV]] = None):
        """
        Инициализация генератора сигналов.

        Args:
            ohlcv_data: Исторические свечи для инициализации ARM
        """
        try:
            from src.strategies.modules.adaptive_regime_manager import \
                RegimeConfig

            # Инициализация ARM
            adaptive_regime_config = getattr(self.config, "adaptive_regime", {})
            if adaptive_regime_config and adaptive_regime_config.get("enabled", True):
                try:
                    regime_config = RegimeConfig(
                        enabled=True,
                        # Параметры детекции из конфига
                        trending_adx_threshold=adaptive_regime_config.get(
                            "detection", {}
                        ).get("trending_adx_threshold", 20.0),
                        ranging_adx_threshold=adaptive_regime_config.get(
                            "detection", {}
                        ).get("ranging_adx_threshold", 15.0),
                        high_volatility_threshold=adaptive_regime_config.get(
                            "detection", {}
                        ).get("high_volatility_threshold", 0.03),
                        lookback_candles=adaptive_regime_config.get(
                            "detection", {}
                        ).get("lookback_candles", 50),
                        adx_period=adaptive_regime_config.get("detection", {}).get(
                            "adx_period", 9
                        ),
                    )
                    self.regime_manager = AdaptiveRegimeManager(regime_config)

                    if ohlcv_data:
                        await self.regime_manager.initialize(ohlcv_data)

                    logger.info("✅ Adaptive Regime Manager инициализирован для Futures")
                except Exception as e:
                    logger.warning(f"⚠️ ARM инициализация не удалась: {e}")
                    self.regime_manager = None
            else:
                logger.info("⚠️ Adaptive Regime Manager отключен в конфиге")

            self.is_initialized = True
            logger.info("✅ FuturesSignalGenerator инициализирован")

        except Exception as e:
            logger.error(f"Ошибка инициализации FuturesSignalGenerator: {e}")
            self.is_initialized = True  # Все равно продолжаем

    async def generate_signals(self) -> List[Dict[str, Any]]:
        """
        Генерация торговых сигналов

        Returns:
            Список торговых сигналов
        """
        if not self.is_initialized:
            logger.warning("SignalGenerator не инициализирован")
            return []

        try:
            signals = []

            # Генерация сигналов для каждой торговой пары
            for symbol in self.scalping_config.symbols:
                symbol_signals = await self._generate_symbol_signals(symbol)
                signals.extend(symbol_signals)

            # Фильтрация и ранжирование сигналов
            filtered_signals = await self._filter_and_rank_signals(signals)

            # Обновление истории сигналов
            self._update_signal_history(filtered_signals)

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка генерации сигналов: {e}")
            return []

    async def _generate_symbol_signals(self, symbol: str) -> List[Dict[str, Any]]:
        """Генерация сигналов для конкретной торговой пары"""
        try:
            # Получение рыночных данных
            market_data = await self._get_market_data(symbol)
            if not market_data:
                return []

            # Генерация базовых сигналов
            base_signals = await self._generate_base_signals(symbol, market_data)

            # Применение фильтров
            filtered_signals = await self._apply_filters(
                symbol, base_signals, market_data
            )

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка генерации сигналов для {symbol}: {e}")
            return []

    async def _get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Получение рыночных данных"""
        try:
            # Здесь нужно реализовать получение данных через WebSocket или REST API
            # Пока используем заглушку
            # Создаем OHLCV данные
            ohlcv_item = OHLCV(
                timestamp=int(datetime.now().timestamp()),
                symbol=symbol,
                open=49900.0,
                high=50100.0,
                low=49800.0,
                close=50000.0,
                volume=1000.0,
            )

            # Создаем MarketData с правильной структурой
            return MarketData(
                symbol=symbol,
                timeframe="1m",
                ohlcv_data=[ohlcv_item],
            )
        except Exception as e:
            logger.error(f"Ошибка получения данных для {symbol}: {e}")
            return None

    async def _generate_base_signals(
        self, symbol: str, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация базовых торговых сигналов"""
        try:
            signals = []

            # Технические индикаторы
            indicators = self.indicator_manager.calculate_all(market_data)

            # RSI сигналы
            rsi_signals = await self._generate_rsi_signals(
                symbol, indicators, market_data
            )
            signals.extend(rsi_signals)

            # MACD сигналы
            macd_signals = await self._generate_macd_signals(
                symbol, indicators, market_data
            )
            signals.extend(macd_signals)

            # Bollinger Bands сигналы
            bb_signals = await self._generate_bollinger_signals(
                symbol, indicators, market_data
            )
            signals.extend(bb_signals)

            # Moving Average сигналы
            ma_signals = await self._generate_ma_signals(
                symbol, indicators, market_data
            )
            signals.extend(ma_signals)

            return signals

        except Exception as e:
            logger.error(f"Ошибка генерации базовых сигналов для {symbol}: {e}")
            return []

    async def _generate_rsi_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация RSI сигналов"""
        signals = []

        try:
            rsi = indicators.get("rsi", 50)

            # Перепроданность (покупка)
            if rsi < 30:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "rsi_oversold",
                        "strength": (30 - rsi) / 30,  # Нормализованная сила
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": rsi,
                        "confidence": 0.8,
                    }
                )

            # Перекупленность (продажа)
            elif rsi > 70:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "rsi_overbought",
                        "strength": (rsi - 70) / 30,  # Нормализованная сила
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": rsi,
                        "confidence": 0.8,
                    }
                )

        except Exception as e:
            logger.error(f"Ошибка генерации RSI сигналов: {e}")

        return signals

    async def _generate_macd_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация MACD сигналов"""
        signals = []

        try:
            macd = indicators.get("macd", {})
            macd_line = macd.get("macd", 0)
            signal_line = macd.get("signal", 0)
            histogram = macd.get("histogram", 0)

            # Пересечение MACD линии и сигнальной линии
            if macd_line > signal_line and histogram > 0:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "macd_bullish",
                        "strength": min(
                            abs(histogram) / 100, 1.0
                        ),  # Нормализованная сила
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": histogram,
                        "confidence": 0.7,
                    }
                )

            elif macd_line < signal_line and histogram < 0:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "macd_bearish",
                        "strength": min(
                            abs(histogram) / 100, 1.0
                        ),  # Нормализованная сила
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": histogram,
                        "confidence": 0.7,
                    }
                )

        except Exception as e:
            logger.error(f"Ошибка генерации MACD сигналов: {e}")

        return signals

    async def _generate_bollinger_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация Bollinger Bands сигналов"""
        signals = []

        try:
            bb = indicators.get("bollinger_bands", {})
            upper = bb.get("upper", 0)
            lower = bb.get("lower", 0)
            middle = bb.get("middle", 0)
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            # Отскок от нижней полосы (покупка)
            if current_price <= lower and (middle - lower) > 0:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "bb_oversold",
                        "strength": (lower - current_price) / (middle - lower),
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": current_price,
                        "confidence": 0.75,
                    }
                )

            # Отскок от верхней полосы (продажа)
            elif current_price >= upper and (upper - middle) > 0:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "bb_overbought",
                        "strength": (current_price - upper) / (upper - middle),
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": current_price,
                        "confidence": 0.75,
                    }
                )

        except Exception as e:
            logger.error(f"Ошибка генерации Bollinger Bands сигналов: {e}")

        return signals

    async def _generate_ma_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация Moving Average сигналов"""
        signals = []

        try:
            ma_fast = indicators.get("ema_12", 0)
            ma_slow = indicators.get("ema_26", 0)
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            # Пересечение быстрой и медленной MA
            if ma_fast > ma_slow and current_price > ma_fast and ma_slow > 0:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "ma_bullish",
                        "strength": (ma_fast - ma_slow) / ma_slow,
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": ma_fast,
                        "confidence": 0.6,
                    }
                )

            elif ma_fast < ma_slow and current_price < ma_fast and ma_slow > 0:
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "ma_bearish",
                        "strength": (ma_slow - ma_fast) / ma_slow,
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": ma_fast,
                        "confidence": 0.6,
                    }
                )

        except Exception as e:
            logger.error(f"Ошибка генерации Moving Average сигналов: {e}")

        return signals

    async def _apply_filters(
        self, symbol: str, signals: List[Dict[str, Any]], market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Применение фильтров к сигналам"""
        try:
            filtered_signals = []

            for signal in signals:
                # Проверка режима рынка
                if not await self.regime_manager.is_signal_valid(signal, market_data):
                    continue

                # Проверка корреляции
                if not await self.correlation_filter.is_signal_valid(
                    signal, market_data
                ):
                    continue

                # Проверка мультитаймфрейма
                if not await self.mtf_filter.is_signal_valid(signal, market_data):
                    continue

                # Проверка pivot points
                if not await self.pivot_filter.is_signal_valid(signal, market_data):
                    continue

                # Проверка volume profile
                if not await self.volume_filter.is_signal_valid(signal, market_data):
                    continue

                # Адаптация под Futures специфику
                futures_signal = await self._adapt_signal_for_futures(signal)
                filtered_signals.append(futures_signal)

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка применения фильтров: {e}")
            return signals

    async def _adapt_signal_for_futures(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Адаптация сигнала под Futures специфику"""
        try:
            # Добавление Futures-специфичных параметров
            futures_signal = signal.copy()

            # Учет левериджа в силе сигнала
            leverage = 3  # Futures по умолчанию 3x
            futures_signal["leverage_adjusted_strength"] = signal["strength"] * (
                leverage / 3
            )

            # Добавление параметров маржи
            futures_signal["margin_required"] = True
            futures_signal["liquidation_risk"] = self._calculate_liquidation_risk(
                signal
            )

            # Адаптация размера позиции
            futures_signal[
                "max_position_size"
            ] = await self._calculate_max_position_size(signal)

            return futures_signal

        except Exception as e:
            logger.error(f"Ошибка адаптации сигнала под Futures: {e}")
            return signal

    def _calculate_liquidation_risk(self, signal: Dict[str, Any]) -> float:
        """Расчет риска ликвидации"""
        try:
            # Упрощенный расчет риска ликвидации
            leverage = self.config.futures.get("leverage", 3)
            strength = signal.get("strength", 0.5)

            # Чем выше леверидж и ниже сила сигнала, тем выше риск
            risk = (leverage / 10) * (1 - strength)
            return min(risk, 1.0)

        except Exception as e:
            logger.error(f"Ошибка расчета риска ликвидации: {e}")
            return 0.5

    async def _calculate_max_position_size(self, signal: Dict[str, Any]) -> float:
        """Расчет максимального размера позиции"""
        try:
            # Здесь нужно интегрироваться с MarginCalculator
            # Пока используем упрощенный расчет
            base_size = 0.001  # Базовый размер
            strength = signal.get("strength", 0.5)

            return base_size * strength

        except Exception as e:
            logger.error(f"Ошибка расчета максимального размера позиции: {e}")
            return 0.001

    async def _filter_and_rank_signals(
        self, signals: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Фильтрация и ранжирование сигналов"""
        try:
            # Фильтрация по минимальной силе
            min_strength = self.scalping_config.min_signal_strength
            filtered_signals = [
                s for s in signals if s.get("strength", 0) >= min_strength
            ]

            # Ранжирование по силе и уверенности
            ranked_signals = sorted(
                filtered_signals,
                key=lambda x: (
                    x.get("strength", 0) * x.get("confidence", 0),
                    x.get("strength", 0),
                ),
                reverse=True,
            )

            # Ограничение количества сигналов
            max_signals = self.scalping_config.max_concurrent_signals
            return ranked_signals[:max_signals]

        except Exception as e:
            logger.error(f"Ошибка фильтрации и ранжирования сигналов: {e}")
            return signals

    def _update_signal_history(self, signals: List[Dict[str, Any]]):
        """Обновление истории сигналов"""
        try:
            timestamp = datetime.now()

            for signal in signals:
                signal_record = {
                    "timestamp": timestamp,
                    "symbol": signal.get("symbol"),
                    "side": signal.get("side"),
                    "strength": signal.get("strength"),
                    "type": signal.get("type"),
                }

                self.signal_history.append(signal_record)

            # Ограничение истории последними 1000 записями
            if len(self.signal_history) > 1000:
                self.signal_history = self.signal_history[-1000:]

        except Exception as e:
            logger.error(f"Ошибка обновления истории сигналов: {e}")

    def get_signal_statistics(self) -> Dict[str, Any]:
        """Получение статистики сигналов"""
        try:
            if not self.signal_history:
                return {"total_signals": 0}

            # Подсчет по типам сигналов
            signal_types = {}
            for record in self.signal_history:
                signal_type = record.get("type", "unknown")
                signal_types[signal_type] = signal_types.get(signal_type, 0) + 1

            # Подсчет по направлениям
            buy_signals = sum(1 for r in self.signal_history if r.get("side") == "buy")
            sell_signals = sum(
                1 for r in self.signal_history if r.get("side") == "sell"
            )

            return {
                "total_signals": len(self.signal_history),
                "buy_signals": buy_signals,
                "sell_signals": sell_signals,
                "signal_types": signal_types,
                "last_signal_time": self.signal_history[-1]["timestamp"]
                if self.signal_history
                else None,
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики сигналов: {e}")
            return {"error": str(e)}


# Пример использования
if __name__ == "__main__":
    # Создаем конфигурацию
    config = BotConfig(
        api_key="test_key",
        secret_key="test_secret",
        passphrase="test_passphrase",
        sandbox=True,
        scalping=ScalpingConfig(
            symbols=["BTC-USDT", "ETH-USDT"],
            min_signal_strength=0.3,
            max_concurrent_signals=5,
        ),
    )

    # Создаем генератор сигналов
    generator = FuturesSignalGenerator(config)

    print("FuturesSignalGenerator готов к работе")
