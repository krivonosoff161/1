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

    def __init__(self, config: BotConfig, client=None):
        """
        Инициализация Futures Signal Generator

        Args:
            config: Конфигурация бота
            client: OKX клиент (опционально, для фильтров)
        """
        self.config = config
        self.scalping_config = config.scalping
        self.client = client  # ✅ Сохраняем клиент для фильтров

        # Менеджер индикаторов
        from src.indicators import (ATR, MACD, RSI, BollingerBands,
                                    ExponentialMovingAverage,
                                    SimpleMovingAverage)

        self.indicator_manager = IndicatorManager()
        # ✅ Добавляем ВСЕ необходимые индикаторы для генерации сигналов
        self.indicator_manager.add_indicator(
            "RSI", RSI(period=14, overbought=70, oversold=30)
        )
        self.indicator_manager.add_indicator("ATR", ATR(period=14))
        self.indicator_manager.add_indicator("SMA", SimpleMovingAverage(period=20))
        # ✅ Добавляем индикаторы, которые используются в генерации сигналов
        self.indicator_manager.add_indicator(
            "MACD", MACD(fast_period=12, slow_period=26, signal_period=9)
        )
        # ✅ ИСПРАВЛЕНИЕ: BollingerBands использует std_multiplier, а не std_dev
        self.indicator_manager.add_indicator(
            "BollingerBands", BollingerBands(period=20, std_multiplier=2.0)
        )
        self.indicator_manager.add_indicator(
            "EMA_12", ExponentialMovingAverage(period=12)
        )
        self.indicator_manager.add_indicator(
            "EMA_26", ExponentialMovingAverage(period=26)
        )

        logger.debug(
            "📊 Инициализированы индикаторы: RSI, ATR, SMA, MACD, BollingerBands, EMA_12, EMA_26"
        )

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
            # ⚠️ ИСПРАВЛЕНИЕ: adaptive_regime находится в config.scalping, а не в config
            scalping_config = getattr(self.config, "scalping", None)
            adaptive_regime_config = None
            if scalping_config:
                if hasattr(scalping_config, "adaptive_regime"):
                    adaptive_regime_config = getattr(
                        scalping_config, "adaptive_regime", None
                    )
                elif isinstance(scalping_config, dict):
                    adaptive_regime_config = scalping_config.get("adaptive_regime", {})

            # Если adaptive_regime_config - это Pydantic модель, проверяем enabled
            enabled = False
            if adaptive_regime_config:
                if hasattr(adaptive_regime_config, "enabled"):
                    enabled = getattr(adaptive_regime_config, "enabled", False)
                elif isinstance(adaptive_regime_config, dict):
                    enabled = adaptive_regime_config.get("enabled", False)

            if adaptive_regime_config and enabled:
                try:
                    # Получаем detection секцию (может быть dict или атрибут)
                    detection = None
                    if isinstance(adaptive_regime_config, dict):
                        detection = adaptive_regime_config.get("detection", {})
                    elif hasattr(adaptive_regime_config, "detection"):
                        detection = getattr(adaptive_regime_config, "detection", {})

                    if isinstance(detection, dict):
                        detection_dict = detection
                    elif hasattr(detection, "__dict__"):
                        detection_dict = (
                            detection.__dict__ if hasattr(detection, "__dict__") else {}
                        )
                    else:
                        detection_dict = {}

                    regime_config = RegimeConfig(
                        enabled=True,
                        # Параметры детекции из конфига
                        trending_adx_threshold=detection_dict.get(
                            "trending_adx_threshold", 20.0
                        ),
                        ranging_adx_threshold=detection_dict.get(
                            "ranging_adx_threshold", 15.0
                        ),
                        high_volatility_threshold=detection_dict.get(
                            "high_volatility_threshold", 0.03
                        ),
                        # lookback_candles и adx_period используются внутри, но не передаются в RegimeConfig
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
        """Получение рыночных данных - исторические свечи для индикаторов"""
        try:
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем ИСТОРИЧЕСКИЕ СВЕЧИ через REST API
            # Индикаторы (RSI, MACD и т.д.) требуют минимум 14-20 свечей для расчета!
            import time

            import aiohttp

            # Получаем последние 50 свечей 1m для расчета индикаторов
            inst_id = f"{symbol}-SWAP"
            url = f"https://www.okx.com/api/v5/market/candles?instId={inst_id}&bar=1m&limit=50"

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == "0" and data.get("data"):
                            candles = data["data"]

                            # Конвертируем свечи из формата OKX в OHLCV
                            # OKX формат: [timestamp, open, high, low, close, volume, volumeCcy]
                            ohlcv_data = []
                            for candle in candles:
                                if len(candle) >= 6:
                                    ohlcv_item = OHLCV(
                                        timestamp=int(candle[0])
                                        // 1000,  # OKX возвращает в миллисекундах
                                        symbol=symbol,
                                        open=float(candle[1]),
                                        high=float(candle[2]),
                                        low=float(candle[3]),
                                        close=float(candle[4]),
                                        volume=float(candle[5]),
                                    )
                                    ohlcv_data.append(ohlcv_item)

                            if ohlcv_data:
                                # Сортируем по timestamp (старые -> новые)
                                ohlcv_data.sort(key=lambda x: x.timestamp)

                                logger.debug(
                                    f"📊 Получено {len(ohlcv_data)} свечей для {symbol}"
                                )

                                # Создаем MarketData с историческими свечами
                                return MarketData(
                                    symbol=symbol,
                                    timeframe="1m",
                                    ohlcv_data=ohlcv_data,
                                )
            logger.warning(f"⚠️ Не удалось получить исторические свечи для {symbol}")
            return None

        except Exception as e:
            logger.error(f"Ошибка получения данных для {symbol}: {e}", exc_info=True)
            return None

    async def _generate_base_signals(
        self, symbol: str, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация базовых торговых сигналов"""
        try:
            signals = []

            # Технические индикаторы
            indicator_results = self.indicator_manager.calculate_all(market_data)

            # ✅ ИСПРАВЛЕНИЕ: Конвертируем IndicatorResult в простой dict с значениями
            # indicator_results содержит объекты IndicatorResult, нужно извлечь значения
            indicators = {}
            for name, result in indicator_results.items():
                if hasattr(result, "value") and hasattr(result, "metadata"):
                    # Если это IndicatorResult, извлекаем данные правильно
                    if name.lower() == "macd":
                        # MACD: value = macd_line, metadata содержит macd_line, signal_line
                        metadata = result.metadata or {}
                        indicators["macd"] = {
                            "macd": metadata.get("macd_line", result.value),
                            "signal": metadata.get("signal_line", result.value),
                            "histogram": metadata.get("macd_line", result.value)
                            - metadata.get("signal_line", result.value),
                        }
                    elif name.lower() == "bollingerbands":
                        # BollingerBands: value = sma (middle), metadata содержит upper_band, lower_band
                        metadata = result.metadata or {}
                        indicators["bollinger_bands"] = {
                            "upper": metadata.get("upper_band", result.value),
                            "lower": metadata.get("lower_band", result.value),
                            "middle": result.value,  # middle = SMA
                        }
                    elif isinstance(result.value, dict):
                        # Для других сложных индикаторов value может быть dict
                        indicators[name.lower()] = result.value
                    else:
                        # Для простых индикаторов (RSI, ATR, SMA, EMA) - просто число
                        indicators[name.lower()] = result.value
                elif isinstance(result, dict):
                    # Если уже dict
                    indicators[name.lower()] = result
                else:
                    # Fallback
                    indicators[name.lower()] = result

            rsi_val = indicators.get("rsi", "N/A")
            macd_val = indicators.get("macd", {})
            if isinstance(macd_val, dict):
                macd_str = f"macd={macd_val.get('macd', 'N/A')}, signal={macd_val.get('signal', 'N/A')}"
            else:
                macd_str = str(macd_val)
            logger.debug(
                f"📊 Индикаторы для {symbol}: RSI={rsi_val}, MACD={{{macd_str}}}"
            )

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
                # ✅ ИСПРАВЛЕНИЕ: Проверяем что фильтры инициализированы перед вызовом
                # Проверка режима рынка (если ARM включен)
                if self.regime_manager:
                    try:
                        if not await self.regime_manager.is_signal_valid(
                            signal, market_data
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован ARM")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки ARM для {symbol}: {e}, пропускаем фильтр"
                        )

                # Проверка корреляции (если фильтр инициализирован)
                if self.correlation_filter:
                    try:
                        if not await self.correlation_filter.is_signal_valid(
                            signal, market_data
                        ):
                            logger.debug(
                                f"🔍 Сигнал {symbol} отфильтрован CorrelationFilter"
                            )
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки CorrelationFilter для {symbol}: {e}, пропускаем фильтр"
                        )

                # Проверка мультитаймфрейма (если фильтр инициализирован)
                if self.mtf_filter:
                    try:
                        if not await self.mtf_filter.is_signal_valid(
                            signal, market_data
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован MTF")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки MTF для {symbol}: {e}, пропускаем фильтр"
                        )

                # Проверка pivot points (если фильтр инициализирован)
                if self.pivot_filter:
                    try:
                        if not await self.pivot_filter.is_signal_valid(
                            signal, market_data
                        ):
                            logger.debug(f"🔍 Сигнал {symbol} отфильтрован PivotPoints")
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки PivotPoints для {symbol}: {e}, пропускаем фильтр"
                        )

                # Проверка volume profile (если фильтр инициализирован)
                if self.volume_filter:
                    try:
                        if not await self.volume_filter.is_signal_valid(
                            signal, market_data
                        ):
                            logger.debug(
                                f"🔍 Сигнал {symbol} отфильтрован VolumeProfile"
                            )
                            continue
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Ошибка проверки VolumeProfile для {symbol}: {e}, пропускаем фильтр"
                        )

                # Адаптация под Futures специфику
                futures_signal = await self._adapt_signal_for_futures(signal)
                filtered_signals.append(futures_signal)

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка применения фильтров: {e}", exc_info=True)
            # В случае ошибки возвращаем сигналы без фильтрации
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
            # ✅ ИСПРАВЛЕНИЕ: Получаем leverage из scalping_config или используем значение по умолчанию
            leverage = getattr(self.scalping_config, "leverage", 3)
            # Если leverage не в scalping_config, используем дефолт 3x для Futures
            if leverage is None:
                leverage = 3

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
