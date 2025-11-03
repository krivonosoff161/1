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

        # ✅ ИСПРАВЛЕНИЕ: Получаем базовые периоды из конфига (из ranging как fallback)
        # Эти периоды используются для базовых расчетов, конкретные режимы используют свои параметры
        rsi_period = 14
        rsi_overbought = 70
        rsi_oversold = 30
        atr_period = 14
        sma_period = 20
        macd_fast = 12
        macd_slow = 26
        macd_signal = 9
        bb_period = 20
        bb_std_multiplier = 2.0
        ema_fast = 12
        ema_slow = 26

        # Получаем базовые параметры из конфига
        try:
            scalping_config = getattr(self.config, "scalping", None)
            if scalping_config:
                # Базовые параметры из scalping секции (если есть)
                if hasattr(scalping_config, "rsi_period"):
                    rsi_period = getattr(scalping_config, "rsi_period", 14)
                if hasattr(scalping_config, "rsi_overbought"):
                    rsi_overbought = getattr(scalping_config, "rsi_overbought", 70)
                if hasattr(scalping_config, "rsi_oversold"):
                    rsi_oversold = getattr(scalping_config, "rsi_oversold", 30)
                if hasattr(scalping_config, "macd_fast"):
                    macd_fast = getattr(scalping_config, "macd_fast", 12)
                if hasattr(scalping_config, "macd_slow"):
                    macd_slow = getattr(scalping_config, "macd_slow", 26)
                if hasattr(scalping_config, "macd_signal"):
                    macd_signal = getattr(scalping_config, "macd_signal", 9)
                if hasattr(scalping_config, "bb_period"):
                    bb_period = getattr(scalping_config, "bb_period", 20)
                if hasattr(scalping_config, "bb_std_dev"):
                    bb_std_multiplier = getattr(scalping_config, "bb_std_dev", 2.0)
                if hasattr(scalping_config, "ma_fast"):
                    ema_fast = getattr(scalping_config, "ma_fast", 12)
                if hasattr(scalping_config, "ma_slow"):
                    ema_slow = getattr(scalping_config, "ma_slow", 26)

                # Пытаемся получить периоды из ranging режима (как базовые)
                adaptive_regime = getattr(scalping_config, "adaptive_regime", None)
                if adaptive_regime:
                    ranging_params = None
                    if hasattr(adaptive_regime, "ranging_params"):
                        ranging_params = getattr(
                            adaptive_regime, "ranging_params", None
                        )
                    elif isinstance(adaptive_regime, dict):
                        ranging_params = adaptive_regime.get("ranging_params", {})

                    if ranging_params:
                        indicators = None
                        if hasattr(ranging_params, "indicators"):
                            indicators = getattr(ranging_params, "indicators", {})
                        elif isinstance(ranging_params, dict):
                            indicators = ranging_params.get("indicators", {})

                        if indicators:
                            # Используем периоды из ranging режима как базовые
                            if isinstance(indicators, dict):
                                # Из dict
                                if "sma_fast" in indicators:
                                    sma_period = indicators.get(
                                        "sma_fast", 20
                                    )  # Используем fast как базовый SMA
                                if "ema_fast" in indicators:
                                    ema_fast = indicators.get("ema_fast", 12)
                                if "ema_slow" in indicators:
                                    ema_slow = indicators.get("ema_slow", 26)
                                if "atr_period" in indicators:
                                    atr_period = indicators.get("atr_period", 14)
                            elif hasattr(indicators, "sma_fast"):
                                # Из атрибутов Pydantic модели
                                sma_period = getattr(indicators, "sma_fast", 20)
                                ema_fast = getattr(indicators, "ema_fast", 12)
                                ema_slow = getattr(indicators, "ema_slow", 26)
                                atr_period = getattr(indicators, "atr_period", 14)
        except Exception as e:
            logger.debug(
                f"⚠️ Не удалось получить периоды индикаторов из конфига: {e}, используем дефолтные"
            )

        # ✅ Добавляем индикаторы с параметрами из конфига
        self.indicator_manager.add_indicator(
            "RSI",
            RSI(period=rsi_period, overbought=rsi_overbought, oversold=rsi_oversold),
        )
        self.indicator_manager.add_indicator("ATR", ATR(period=atr_period))
        self.indicator_manager.add_indicator(
            "SMA", SimpleMovingAverage(period=sma_period)
        )
        # ✅ Добавляем индикаторы, которые используются в генерации сигналов
        self.indicator_manager.add_indicator(
            "MACD",
            MACD(
                fast_period=macd_fast, slow_period=macd_slow, signal_period=macd_signal
            ),
        )
        # ✅ ИСПРАВЛЕНИЕ: BollingerBands использует std_multiplier, а не std_dev
        self.indicator_manager.add_indicator(
            "BollingerBands",
            BollingerBands(period=bb_period, std_multiplier=bb_std_multiplier),
        )
        self.indicator_manager.add_indicator(
            "EMA_12", ExponentialMovingAverage(period=ema_fast)
        )
        self.indicator_manager.add_indicator(
            "EMA_26", ExponentialMovingAverage(period=ema_slow)
        )

        logger.debug(
            f"📊 Инициализированы индикаторы с параметрами из конфига: "
            f"RSI(period={rsi_period}), ATR({atr_period}), SMA({sma_period}), "
            f"MACD({macd_fast}/{macd_slow}/{macd_signal}), BB({bb_period}), "
            f"EMA({ema_fast}/{ema_slow})"
        )

        # Модули фильтрации - ИНТЕГРАЦИЯ адаптивных систем
        self.regime_manager = (
            None  # Инициализируется в initialize() (общий для всех символов)
        )
        self.regime_managers = {}  # ✅ Отдельный ARM для каждого символа
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

                    # ✅ Создаем отдельный ARM для каждого символа
                    for symbol in self.scalping_config.symbols:
                        symbol_regime_config = (
                            regime_config  # Можно настроить индивидуально
                        )
                        self.regime_managers[symbol] = AdaptiveRegimeManager(
                            symbol_regime_config
                        )
                        # Инициализируем если есть данные
                        if ohlcv_data and symbol in ohlcv_data:
                            await self.regime_managers[symbol].initialize(
                                {symbol: ohlcv_data[symbol]}
                            )

                    logger.info(
                        f"✅ Adaptive Regime Manager инициализирован: "
                        f"общий + {len(self.regime_managers)} для символов"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ ARM инициализация не удалась: {e}")
                    self.regime_manager = None
            else:
                logger.info("⚠️ Adaptive Regime Manager отключен в конфиге")

            # ✅ Инициализация Multi-Timeframe фильтра
            try:
                from src.strategies.modules.multi_timeframe import (
                    MTFConfig, MultiTimeframeFilter)

                # Создаем конфигурацию MTF (можно взять из config если есть)
                mtf_config = MTFConfig(
                    confirmation_timeframe="5m",  # Проверяем тренд на 5m
                    score_bonus=2,
                    block_opposite=True,  # Блокируем противоположные сигналы
                    ema_fast_period=8,
                    ema_slow_period=21,
                    cache_ttl_seconds=30,  # Кэш на 30 секунд
                )

                # Инициализируем MTF фильтр (client может быть None - свечи получаем напрямую)
                self.mtf_filter = MultiTimeframeFilter(
                    client=self.client, config=mtf_config  # Может быть None
                )

                logger.info(
                    f"✅ Multi-Timeframe Filter инициализирован: "
                    f"таймфрейм={mtf_config.confirmation_timeframe}, "
                    f"block_opposite={mtf_config.block_opposite}"
                )
            except Exception as e:
                logger.warning(f"⚠️ MTF инициализация не удалась: {e}")
                self.mtf_filter = None

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
            # ✅ Детекция режима для каждого символа отдельно
            for symbol in self.scalping_config.symbols:
                # Получаем данные один раз для символа (оптимизация)
                market_data = await self._get_market_data(symbol)
                if not market_data:
                    continue

                # Обновляем режим ARM для текущего символа (используем персональный ARM если есть)
                regime_manager = self.regime_managers.get(symbol) or self.regime_manager

                if (
                    regime_manager
                    and market_data.ohlcv_data
                    and len(market_data.ohlcv_data) >= 50
                ):
                    try:
                        # Берем последнюю цену закрытия как current_price
                        current_price = market_data.ohlcv_data[-1].close

                        # Обновляем режим на основе свежих данных (detect_regime не async)
                        detection_result = regime_manager.detect_regime(
                            market_data.ohlcv_data, current_price
                        )
                        current_regime = regime_manager.get_current_regime()
                        logger.debug(
                            f"🧠 ARM режим для {symbol}: {current_regime} "
                            f"(confidence: {detection_result.confidence:.1%})"
                        )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка обновления режима ARM для {symbol}: {e}"
                        )

                # Генерируем сигналы для текущего символа (передаем уже полученные данные)
                symbol_signals = await self._generate_symbol_signals(
                    symbol, market_data
                )
                signals.extend(symbol_signals)

            # Фильтрация и ранжирование сигналов
            filtered_signals = await self._filter_and_rank_signals(signals)

            # Обновление истории сигналов
            self._update_signal_history(filtered_signals)

            return filtered_signals

        except Exception as e:
            logger.error(f"Ошибка генерации сигналов: {e}")
            return []

    async def _generate_symbol_signals(
        self, symbol: str, market_data: Optional[MarketData] = None
    ) -> List[Dict[str, Any]]:
        """Генерация сигналов для конкретной торговой пары

        Args:
            symbol: Торговая пара
            market_data: Рыночные данные (если не переданы - получим сами)
        """
        try:
            # Получение рыночных данных (если не переданы)
            if not market_data:
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
                macd_line = macd_val.get("macd", 0)
                signal_line = macd_val.get("signal", 0)
                histogram = macd_line - signal_line
                macd_str = (
                    f"macd={macd_line}, signal={signal_line}, histogram={histogram}"
                )
            else:
                macd_str = str(macd_val)

            # Добавляем EMA и BB для диагностики
            ema_12 = indicators.get("ema_12", 0)
            ema_26 = indicators.get("ema_26", 0)
            bb = indicators.get("bollinger_bands", {})
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            logger.debug(
                f"📊 Индикаторы для {symbol}:\n"
                f"   Цена: ${current_price:.2f}\n"
                f"   RSI: {rsi_val}\n"
                f"   MACD: {{{macd_str}}}\n"
                f"   EMA: 12={ema_12:.2f}, 26={ema_26:.2f}\n"
                f"   BB: upper={bb.get('upper', 0):.2f}, lower={bb.get('lower', 0):.2f}, middle={bb.get('middle', 0):.2f}"
            )

            # RSI сигналы
            rsi_signals = await self._generate_rsi_signals(
                symbol, indicators, market_data
            )
            if rsi_signals:
                logger.debug(f"✅ RSI дал {len(rsi_signals)} сигнал(ов) для {symbol}")
            signals.extend(rsi_signals)

            # MACD сигналы
            macd_signals = await self._generate_macd_signals(
                symbol, indicators, market_data
            )
            if macd_signals:
                logger.debug(
                    f"✅ MACD дал {len(macd_signals)} сигнал(ов) для {symbol}: {[s.get('type') for s in macd_signals]}"
                )
            signals.extend(macd_signals)

            # Bollinger Bands сигналы
            bb_signals = await self._generate_bollinger_signals(
                symbol, indicators, market_data
            )
            if bb_signals:
                logger.debug(
                    f"✅ Bollinger Bands дал {len(bb_signals)} сигнал(ов) для {symbol}: {[s.get('type') for s in bb_signals]}"
                )
            signals.extend(bb_signals)

            # Moving Average сигналы
            ma_signals = await self._generate_ma_signals(
                symbol, indicators, market_data
            )
            if ma_signals:
                logger.debug(
                    f"✅ Moving Average дал {len(ma_signals)} сигнал(ов) для {symbol}: {[s.get('type') for s in ma_signals]}"
                )
            signals.extend(ma_signals)

            logger.debug(
                f"📊 Всего базовых сигналов для {symbol}: {len(signals)} ({[s.get('type', 'unknown') for s in signals]})"
            )

            return signals

        except Exception as e:
            logger.error(f"Ошибка генерации базовых сигналов для {symbol}: {e}")
            return []

    def _get_regime_indicators_params(
        self, regime: str = None, symbol: str = None
    ) -> Dict:
        """
        Получить параметры индикаторов для режима из конфига.

        Args:
            regime: Режим ("trending"/"ranging"/"choppy") или None для текущего режима
            symbol: Символ для получения режима (использует персональный ARM если есть)

        Returns:
            Dict с параметрами индикаторов
        """
        # Используем персональный ARM для символа или общий
        regime_manager = None
        if symbol and symbol in self.regime_managers:
            regime_manager = self.regime_managers[symbol]
        elif self.regime_manager:
            regime_manager = self.regime_manager

        if not regime_manager:
            # Fallback: используем ranging параметры
            regime = "ranging"
        elif regime is None:
            # Получаем текущий режим от ARM
            regime = regime_manager.get_current_regime() or "ranging"

        # Получаем параметры режима из конфига
        try:
            scalping_config = getattr(self.config, "scalping", None)
            if scalping_config:
                adaptive_regime = getattr(scalping_config, "adaptive_regime", None)
                if adaptive_regime:
                    regime_params = getattr(adaptive_regime, f"{regime}_params", None)
                    if regime_params:
                        indicators = getattr(regime_params, "indicators", {})
                        if indicators:
                            return indicators
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить параметры режима {regime}: {e}")

        # Дефолтные значения (ranging)
        return {
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "ema_fast": 10,
            "ema_slow": 25,
        }

    async def _generate_rsi_signals(
        self, symbol: str, indicators: Dict, market_data: MarketData
    ) -> List[Dict[str, Any]]:
        """Генерация RSI сигналов с режим-специфичными порогами"""
        signals = []

        try:
            rsi = indicators.get("rsi", 50)

            # ✅ Получаем режим-специфичные параметры для текущего символа
            regime_params = self._get_regime_indicators_params(symbol=symbol)
            rsi_oversold = regime_params.get("rsi_oversold", 30)
            rsi_overbought = regime_params.get("rsi_overbought", 70)

            # Получаем текущий режим для логирования
            regime_manager = self.regime_managers.get(symbol) or self.regime_manager
            current_regime = (
                regime_manager.get_current_regime() if regime_manager else "N/A"
            )

            logger.debug(
                f"📊 RSI для {symbol}: значение={rsi:.2f}, "
                f"пороги oversold={rsi_oversold}, overbought={rsi_overbought} "
                f"(режим: {current_regime})"
            )

            # Перепроданность (покупка) - используем адаптивный порог
            if rsi < rsi_oversold:
                # Нормализованная сила: от 0 до 1
                strength = min(1.0, (rsi_oversold - rsi) / rsi_oversold)
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",
                        "type": "rsi_oversold",
                        "strength": strength,
                        "price": market_data.ohlcv_data[-1].close
                        if market_data.ohlcv_data
                        else 0.0,
                        "timestamp": datetime.now(),
                        "indicator_value": rsi,
                        "confidence": 0.8,
                    }
                )

            # Перекупленность (продажа) - используем адаптивный порог
            elif rsi > rsi_overbought:
                # Нормализованная сила: от 0 до 1
                strength = min(1.0, (rsi - rsi_overbought) / (100 - rsi_overbought))
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "type": "rsi_overbought",
                        "strength": strength,
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
            # ✅ ИСПРАВЛЕНИЕ: Правильно вычисляем histogram
            histogram = macd.get("histogram", macd_line - signal_line)

            logger.debug(
                f"🔍 MACD для {symbol}: macd_line={macd_line:.4f}, "
                f"signal_line={signal_line:.4f}, histogram={histogram:.4f}"
            )

            # Пересечение MACD линии и сигнальной линии
            if macd_line > signal_line and histogram > 0:
                logger.debug(
                    f"✅ MACD BULLISH сигнал для {symbol}: macd({macd_line:.4f}) > signal({signal_line:.4f}), "
                    f"histogram={histogram:.4f} > 0"
                )
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
                logger.debug(
                    f"✅ MACD BEARISH сигнал для {symbol}: macd({macd_line:.4f}) < signal({signal_line:.4f}), "
                    f"histogram={histogram:.4f} < 0"
                )
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

            logger.debug(
                f"🔍 BB для {symbol}: цена={current_price:.2f}, upper={upper:.2f}, "
                f"lower={lower:.2f}, middle={middle:.2f}, "
                f"цена<=lower={current_price <= lower if lower > 0 else False}, "
                f"цена>=upper={current_price >= upper if upper > 0 else False}"
            )

            # Отскок от нижней полосы (покупка)
            if current_price <= lower and (middle - lower) > 0:
                logger.debug(
                    f"✅ BB OVERSOLD сигнал для {symbol}: цена({current_price:.2f}) <= lower({lower:.2f})"
                )
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
                logger.debug(
                    f"✅ BB OVERBOUGHT сигнал для {symbol}: цена({current_price:.2f}) >= upper({upper:.2f})"
                )
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
        """Генерация Moving Average сигналов с проверкой направления движения цены"""
        signals = []

        try:
            ma_fast = indicators.get("ema_12", 0)
            ma_slow = indicators.get("ema_26", 0)
            current_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            # ✅ УЛУЧШЕНИЕ: Проверяем направление движения цены (последние 3-5 свечей)
            price_direction = None  # "up", "down", "neutral"
            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= 5:
                # Берем последние 5 свечей для определения направления
                recent_candles = market_data.ohlcv_data[-5:]
                closes = [c.close for c in recent_candles]

                # Сравниваем первую и последнюю цену в окне
                price_change = (
                    (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0
                )

                # Определяем направление (порог 0.05% чтобы избежать шума)
                if price_change > 0.0005:  # Рост > 0.05%
                    price_direction = "up"
                elif price_change < -0.0005:  # Падение > 0.05%
                    price_direction = "down"
                else:
                    price_direction = "neutral"

                # Также проверяем последние 3 свечи для более быстрой реакции
                if len(recent_candles) >= 3:
                    short_closes = [c.close for c in recent_candles[-3:]]
                    short_change = (
                        (short_closes[-1] - short_closes[0]) / short_closes[0]
                        if short_closes[0] > 0
                        else 0
                    )
                    # Если короткий тренд сильнее - используем его
                    if abs(short_change) > abs(price_change) * 1.5:
                        if short_change > 0.0005:
                            price_direction = "up"
                        elif short_change < -0.0005:
                            price_direction = "down"

            # ✅ ДИАГНОСТИКА: Логируем значения для анализа
            logger.debug(
                f"🔍 MA для {symbol}: EMA_12={ma_fast:.2f}, EMA_26={ma_slow:.2f}, "
                f"цена={current_price:.2f}, ma_fast>ma_slow={ma_fast > ma_slow}, "
                f"цена>ma_fast={current_price > ma_fast if ma_fast > 0 else False}, "
                f"направление_цены={price_direction}"
            )

            # Пересечение быстрой и медленной MA
            if ma_fast > ma_slow and current_price > ma_fast and ma_slow > 0:
                # ✅ УЛУЧШЕНИЕ: Не даем bullish сигнал если цена падает
                if price_direction == "down":
                    logger.debug(
                        f"⚠️ MA BULLISH сигнал ОТМЕНЕН для {symbol}: "
                        f"EMA показывает bullish, но цена падает (направление={price_direction})"
                    )
                else:
                    strength = (ma_fast - ma_slow) / ma_slow
                    # Снижаем силу сигнала если направление neutral (не подтверждено)
                    if price_direction == "neutral":
                        strength *= 0.7

                    logger.debug(
                        f"✅ MA BULLISH сигнал для {symbol}: EMA_12({ma_fast:.2f}) > EMA_26({ma_slow:.2f}), "
                        f"цена({current_price:.2f}) > EMA_12, направление={price_direction}, strength={strength:.4f}"
                    )
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "ma_bullish",
                            "strength": strength,
                            "price": market_data.ohlcv_data[-1].close
                            if market_data.ohlcv_data
                            else 0.0,
                            "timestamp": datetime.now(),
                            "indicator_value": ma_fast,
                            "confidence": 0.7
                            if price_direction == "up"
                            else 0.5,  # Больше уверенности если цена растет
                        }
                    )

            elif ma_fast < ma_slow and current_price < ma_fast and ma_slow > 0:
                # ✅ УЛУЧШЕНИЕ: Не даем bearish сигнал если цена растет
                if price_direction == "up":
                    logger.debug(
                        f"⚠️ MA BEARISH сигнал ОТМЕНЕН для {symbol}: "
                        f"EMA показывает bearish, но цена растет (направление={price_direction})"
                    )
                else:
                    strength = (ma_slow - ma_fast) / ma_slow
                    # Снижаем силу сигнала если направление neutral
                    if price_direction == "neutral":
                        strength *= 0.7

                    logger.debug(
                        f"✅ MA BEARISH сигнал для {symbol}: EMA_12({ma_fast:.2f}) < EMA_26({ma_slow:.2f}), "
                        f"цена({current_price:.2f}) < EMA_12, направление={price_direction}, strength={strength:.4f}"
                    )
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "ma_bearish",
                            "strength": strength,
                            "price": market_data.ohlcv_data[-1].close
                            if market_data.ohlcv_data
                            else 0.0,
                            "timestamp": datetime.now(),
                            "indicator_value": ma_fast,
                            "confidence": 0.7
                            if price_direction == "down"
                            else 0.5,  # Больше уверенности если цена падает
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
                # Проверка режима рынка (используем персональный ARM для символа если есть)
                regime_manager = self.regime_managers.get(symbol) or self.regime_manager
                if regime_manager:
                    try:
                        if not await regime_manager.is_signal_valid(
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
        secret_key="test_secret",  # nosec B106
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
