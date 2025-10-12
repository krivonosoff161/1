"""
Enhanced Scalping Strategy with Advanced Risk Management
Улучшенная скальпинг стратегия с продвинутым управлением рисками
"""

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
from loguru import logger
from scipy import stats

from src.core.exceptions import RiskLimitExceeded, TradingException
from src.exchange.base import ExchangeClient
from src.indicators.correlation import CorrelationMatrix, MarketRegimeDetector
from src.indicators.technical import AdaptiveMACD, EnhancedRSI, VolatilityBands
from src.indicators.volume import VWAP, OrderBookImbalance, VolumeProfile
from src.models.market import MarketData, Tick
from src.models.trading import OrderSide, OrderType, Position, Signal
from src.strategies.risk_manager import EnhancedRiskManager


class MarketRegime(Enum):
    """Рыночные режимы для адаптации стратегии"""

    TRENDING = "trending"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    NEWS_EVENT = "news_event"


class TradingSession(Enum):
    """Торговые сессии для фильтрации времени"""

    ASIAN = "asian"
    EUROPEAN = "european"
    AMERICAN = "american"
    OVERLAP = "overlap"
    INACTIVE = "inactive"


@dataclass
class EnhancedSignal(Signal):
    """Расширенный сигнал с дополнительными метриками"""

    market_regime: MarketRegime
    volatility_score: float
    correlation_risk: float
    liquidity_score: float
    news_sentiment: Optional[float] = None
    expected_return: Optional[float] = None
    max_risk: Optional[float] = None


class EnhancedScalpingStrategy:
    """
    Продвинутая скальпинг стратегия с улучшениями:

    1. Адаптивные индикаторы - подстройка под волатильность
    2. Многоуровневые TP/SL - пирамидинг выходов
    3. Фильтр времени - торговля только в активные сессии
    4. Корреляционный анализ - защита от системного риска
    5. Kelly Criterion - оптимальный размер позиции
    6. Market regime detection - адаптация под рыночные условия
    7. Order book analysis - анализ глубины рынка
    8. News sentiment integration - учет новостного фона
    """

    def __init__(
        self, client: ExchangeClient, config: dict, risk_manager: EnhancedRiskManager
    ):
        self.client = client
        self.config = config
        self.risk_manager = risk_manager
        self.strategy_id = "enhanced_scalping_v2"

        # Состояние стратегии
        self.active = config.get("enabled", True)
        self.positions: Dict[str, Position] = {}
        self.pending_orders: Dict[str, str] = {}

        # Торговые ограничения
        self.max_trades_per_hour = config.get("max_trades_per_hour", 20)
        self.max_concurrent_positions = config.get("max_concurrent_positions", 5)
        self.min_profit_target = config.get("min_profit_target", 0.0015)  # 0.15%

        # Временные фильтры
        self.trading_hours = {
            TradingSession.ASIAN: (0, 9),  # UTC 00:00-09:00
            TradingSession.EUROPEAN: (7, 16),  # UTC 07:00-16:00
            TradingSession.AMERICAN: (13, 22),  # UTC 13:00-22:00
        }

        # Инициализация компонентов
        self._initialize_indicators()
        self._initialize_filters()
        self._initialize_performance_tracking()

        # Логируем успешную инициализацию стратегии
        symbols_count = len(config.get("symbols", []))
        logger.info(
            f"Enhanced scalping strategy initialized for {symbols_count} symbols"
        )

    def _initialize_indicators(self) -> None:
        """
        Инициализация улучшенных адаптивных индикаторов.

        Создает набор технических индикаторов с возможностью адаптации
        под текущие рыночные условия:
        - EnhancedRSI с адаптивным периодом
        - AdaptiveMACD с корректировкой на волатильность
        - VolatilityBands с динамическими мультипликаторами
        - VWAP и Volume Profile для анализа объёмов
        - OrderBookImbalance для анализа дисбаланса ордеров
        - CorrelationMatrix для мониторинга корреляций
        - MarketRegimeDetector для определения режима рынка
        """
        # Адаптивные технические индикаторы
        self.rsi = EnhancedRSI(
            period=14,
            adaptive_period=True,  # Автоподстройка периода под волатильность
            overbought=70,
            oversold=30,
        )

        # MACD с адаптацией под волатильность рынка
        self.macd = AdaptiveMACD(
            fast_period=12,
            slow_period=26,
            signal_period=9,
            volatility_adjustment=True,
        )

        self.volatility_bands = VolatilityBands(
            period=20,
            multiplier=2.0,
            adaptive_multiplier=True,  # Подстройка под режим рынка
        )

        # Объемные индикаторы
        self.vwap = VWAP(period=200)
        self.volume_profile = VolumeProfile(period=100)
        self.order_book_imbalance = OrderBookImbalance()

        # Корреляционный анализ
        self.correlation_matrix = CorrelationMatrix(
            symbols=self.config.get("symbols", []), lookback_period=50
        )

        # Детектор рыночного режима (тренд, флэт, высокая/низкая волатильность)
        self.regime_detector = MarketRegimeDetector(
            lookback_period=100,
            volatility_threshold=0.02,
            trend_threshold=0.001,
        )

    def _initialize_filters(self) -> None:
        """
        Инициализация фильтров для улучшения качества торговых сигналов.

        Устанавливает пороговые значения для различных рыночных параметров:
        - Минимальная волатильность (избегаем низкой волатильности)
        - Максимальный спред bid-ask (контроль ликвидности)
        - Минимальный объём торгов (фильтр ликвидности)
        - Максимальная корреляция между позициями (диверсификация риска)
        """
        # Фильтр минимальной волатильности
        self.min_volatility_threshold = 0.0008  # 0.08%

        # Фильтр спреда bid-ask
        self.max_spread_bps = 5  # 5 базисных пунктов

        # Фильтр ликвидности
        self.min_volume_threshold = 1000000  # $1M за последний час

        # Фильтр корреляции (защита от системного риска)
        # Максимальная допустимая корреляция между открытыми позициями
        self.max_correlation_exposure = 0.7

    def _initialize_performance_tracking(self) -> None:
        """
        Инициализация системы отслеживания производительности стратегии.

        Создает структуры данных для хранения:
        - Общей статистики сделок (выигрышные, проигрышные)
        - PnL метрик (total PnL, average win/loss)
        - Риск-метрик (максимальная просадка, Sharpe ratio)
        - Kelly Criterion для оптимизации размера позиций
        - Истории сделок для статистического анализа
        """
        self.performance_stats = {
            "total_trades": 0,
            "winning_trades": 0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "kelly_fraction": 0.25,  # Начальная Kelly fraction
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 1.0,
        }

        # История для расчета Kelly Criterion
        self.trade_history: List[float] = []
        self.kelly_calculation_period = 100  # Пересчет Kelly каждые 100 сделок

    async def analyze_market_conditions(
        self, symbol: str, market_data: MarketData
    ) -> dict:
        """
        Анализ текущих рыночных условий

        Returns:
            dict: Словарь с анализом рыночных условий
        """
        conditions = {}

        # Определение рыночного режима
        regime = await self.regime_detector.detect_regime(market_data)
        conditions["market_regime"] = regime

        # Анализ волатильности
        current_volatility = await self._calculate_current_volatility(market_data)
        historical_volatility = await self._calculate_historical_volatility(
            market_data, period=30
        )

        conditions["volatility"] = {
            "current": current_volatility,
            "historical_avg": historical_volatility,
            "percentile": await self._get_volatility_percentile(
                current_volatility, market_data
            ),
        }

        # Анализ ликвидности
        liquidity_metrics = await self._analyze_liquidity(symbol)
        conditions["liquidity"] = liquidity_metrics

        # Определение торговой сессии
        current_session = self._get_current_trading_session()
        conditions["trading_session"] = current_session

        # Анализ order book
        order_book_analysis = await self._analyze_order_book(symbol)
        conditions["order_book"] = order_book_analysis

        return conditions

    async def generate_enhanced_signal(
        self, symbol: str, market_data: MarketData, tick: Tick
    ) -> Optional[EnhancedSignal]:
        """
        Генерация улучшенного торгового сигнала

        Args:
            symbol: Торговый символ
            market_data: Рыночные данные
            tick: Текущий тик

        Returns:
            Optional[EnhancedSignal]: Сигнал или None
        """
        try:
            # Анализ рыночных условий
            market_conditions = await self.analyze_market_conditions(
                symbol, market_data
            )

            # Проверка базовых фильтров
            if not await self._check_basic_filters(symbol, market_conditions):
                return None

            # Расчет технических индикаторов
            indicators = await self._calculate_all_indicators(market_data, tick)

            # Генерация базового сигнала
            base_signal = await self._generate_base_signal(
                symbol, indicators, tick, market_conditions
            )
            if not base_signal:
                return None

            # Улучшение сигнала дополнительными метриками
            enhanced_signal = await self._enhance_signal(
                base_signal, market_conditions, indicators
            )

            # Валидация сигнала через risk manager
            if not await self.risk_manager.validate_signal(enhanced_signal):
                logger.debug(f"Signal rejected by risk manager for {symbol}")
                return None

            return enhanced_signal

        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            return None

    async def _generate_base_signal(
        self, symbol: str, indicators: dict, tick: Tick, market_conditions: dict
    ) -> Optional[Signal]:
        """Генерация базового торгового сигнала"""

        current_price = tick.price
        market_regime = market_conditions["market_regime"]

        # Адаптация параметров под рыночный режим
        if market_regime == MarketRegime.HIGH_VOLATILITY:
            rsi_overbought, rsi_oversold = 75, 25  # Расширенные границы
            min_macd_divergence = 0.0002
        elif market_regime == MarketRegime.LOW_VOLATILITY:
            rsi_overbought, rsi_oversold = 65, 35  # Узкие границы
            min_macd_divergence = 0.0001
        else:
            rsi_overbought, rsi_oversold = 70, 30  # Стандартные границы
            min_macd_divergence = 0.00015

        # Получение значений индикаторов
        rsi_value = indicators.get("rsi", 50)
        macd_line = indicators.get("macd_line", 0)
        macd_signal = indicators.get("macd_signal", 0)
        upper_band = indicators.get("upper_band", current_price * 1.01)
        lower_band = indicators.get("lower_band", current_price * 0.99)
        vwap_value = indicators.get("vwap", current_price)

        # Long сигнал - улучшенные условия
        long_conditions = [
            # RSI в зоне перепроданности или восстановление
            rsi_value < rsi_oversold
            or (30 < rsi_value < 50 and indicators.get("rsi_trend", 0) > 0),
            # MACD бычье пересечение или дивергенция
            (macd_line > macd_signal and macd_line - macd_signal > min_macd_divergence),
            # Цена около нижней полосы волатильности (потенциальный отскок)
            current_price <= lower_band * 1.003,  # 0.3% толерантность
            # Цена выше VWAP или приближение к нему снизу
            current_price > vwap_value * 0.999,
            # Объемное подтверждение
            indicators.get("volume_ratio", 1.0) > 1.2,
            # Order book поддерживает направление
            indicators.get("order_book_bias", 0) >= 0,
        ]

        # Short сигнал - улучшенные условия
        short_conditions = [
            # RSI в зоне перекупленности или ослабление
            rsi_value > rsi_overbought
            or (50 < rsi_value < 70 and indicators.get("rsi_trend", 0) < 0),
            # MACD медвежье пересечение или дивергенция
            (macd_line < macd_signal and macd_signal - macd_line > min_macd_divergence),
            # Цена около верхней полосы волатильности (потенциальный откат)
            current_price >= upper_band * 0.997,  # 0.3% толерантность
            # Цена ниже VWAP или приближение к нему сверху
            current_price < vwap_value * 1.001,
            # Объемное подтверждение
            indicators.get("volume_ratio", 1.0) > 1.2,
            # Order book поддерживает направление
            indicators.get("order_book_bias", 0) <= 0,
        ]

        # Оценка силы сигнала
        long_strength = sum(long_conditions) / len(long_conditions)
        short_strength = sum(short_conditions) / len(short_conditions)

        # Минимальная сила сигнала для входа (ниже на трендах, выше во флэте)
        min_signal_strength = 0.75 if market_regime == MarketRegime.TRENDING else 0.85

        if long_strength >= min_signal_strength and long_strength > short_strength:
            return Signal(
                symbol=symbol,
                side=OrderSide.BUY,
                strength=long_strength,
                price=current_price,
                timestamp=datetime.utcnow(),
                strategy_id=self.strategy_id,
                indicators=indicators,
                confidence=long_strength,
            )
        elif short_strength >= min_signal_strength and short_strength > long_strength:
            return Signal(
                symbol=symbol,
                side=OrderSide.SELL,
                strength=short_strength,
                price=current_price,
                timestamp=datetime.utcnow(),
                strategy_id=self.strategy_id,
                indicators=indicators,
                confidence=short_strength,
            )

        return None

    async def _enhance_signal(
        self, base_signal: Signal, market_conditions: dict, indicators: dict
    ) -> EnhancedSignal:
        """Улучшение базового сигнала дополнительными метриками"""

        # Расчет корреляционного риска
        correlation_risk = await self._calculate_correlation_risk(base_signal.symbol)

        # Расчет ожидаемой доходности на основе исторических данных
        expected_return = await self._calculate_expected_return(
            base_signal.symbol, base_signal.side, market_conditions["market_regime"]
        )

        # Расчет максимального риска для позиции
        max_risk = await self._calculate_position_risk(
            base_signal.symbol, base_signal.price, expected_return
        )

        return EnhancedSignal(
            symbol=base_signal.symbol,
            side=base_signal.side,
            strength=base_signal.strength,
            price=base_signal.price,
            timestamp=base_signal.timestamp,
            strategy_id=base_signal.strategy_id,
            indicators=base_signal.indicators,
            confidence=base_signal.confidence,
            market_regime=market_conditions["market_regime"],
            volatility_score=market_conditions["volatility"]["percentile"],
            correlation_risk=correlation_risk,
            liquidity_score=market_conditions["liquidity"]["score"],
            expected_return=expected_return,
            max_risk=max_risk,
        )

    async def calculate_optimal_position_size(
        self, signal: EnhancedSignal, account_balance: float
    ) -> float:
        """
        Расчет оптимального размера позиции с использованием Kelly Criterion

        Args:
            signal: Торговый сигнал
            account_balance: Баланс счета

        Returns:
            float: Оптимальный размер позиции
        """
        try:
            # Базовый размер позиции (1% от баланса)
            base_risk_amount = account_balance * 0.01

            # Kelly Criterion расчет
            kelly_fraction = self._calculate_kelly_fraction()

            # Корректировка Kelly на основе уверенности в сигнале
            adjusted_kelly = kelly_fraction * signal.confidence

            # Корректировка на рыночный режим
            regime_multiplier = self._get_regime_multiplier(signal.market_regime)
            adjusted_kelly *= regime_multiplier

            # Корректировка на корреляционный риск
            correlation_adjustment = max(0.3, 1.0 - signal.correlation_risk)
            adjusted_kelly *= correlation_adjustment

            # Корректировка на ликвидность
            liquidity_adjustment = min(1.5, signal.liquidity_score)
            adjusted_kelly *= liquidity_adjustment

            # Ограничение максимального размера позиции
            max_position_fraction = 0.1  # Максимум 10% от баланса
            final_fraction = min(adjusted_kelly, max_position_fraction)

            # Расчет размера позиции
            position_value = account_balance * final_fraction
            position_size = position_value / signal.price

            logger.debug(
                f"Position sizing for {signal.symbol}: "
                f"Kelly={kelly_fraction:.3f}, Adjusted={adjusted_kelly:.3f}, "
                f"Final fraction={final_fraction:.3f}, Size={position_size:.6f}"
            )

            return position_size

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            # Возврат к консервативному размеру позиции
            return (account_balance * 0.005) / signal.price  # 0.5% от баланса

    def _calculate_kelly_fraction(self) -> float:
        """
        Расчет Kelly Criterion на основе истории сделок

        Returns:
            float: Kelly fraction (0.0 - 1.0)
        """
        if len(self.trade_history) < 20:
            return 0.25  # Консервативная Kelly fraction для начала

        # Разделение на выигрышные и проигрышные сделки
        wins = [pnl for pnl in self.trade_history if pnl > 0]
        losses = [abs(pnl) for pnl in self.trade_history if pnl < 0]

        if not wins or not losses:
            return 0.25

        # Расчет параметров Kelly
        win_rate = len(wins) / len(self.trade_history)
        avg_win = np.mean(wins)
        avg_loss = np.mean(losses)

        # Kelly formula: f = (bp - q) / b
        # где b = avg_win/avg_loss, p = win_rate, q = 1-win_rate
        b = avg_win / avg_loss
        p = win_rate
        q = 1 - win_rate

        kelly_fraction = (b * p - q) / b

        # Ограничение Kelly fraction разумными пределами
        kelly_fraction = max(0.01, min(0.4, kelly_fraction))

        # Сглаживание с предыдущим значением
        current_kelly = self.performance_stats.get("kelly_fraction", 0.25)
        smoothed_kelly = 0.8 * current_kelly + 0.2 * kelly_fraction

        self.performance_stats["kelly_fraction"] = smoothed_kelly

        return smoothed_kelly

    async def create_multi_level_exit_strategy(
        self, signal: EnhancedSignal, position_size: float
    ) -> List[Tuple[float, float, str]]:
        """
        Создание многоуровневой стратегии выхода (пирамидинг)

        Args:
            signal: Торговый сигнал
            position_size: Размер позиции

        Returns:
            List[Tuple[float, float, str]]: Список (цена, размер, тип) для выходов
        """
        exit_levels = []
        entry_price = signal.price

        # Расчет ATR для динамических уровней
        atr = signal.indicators.get("atr", entry_price * 0.002)  # Fallback 0.2%

        # Адаптация уровней под рыночный режим
        if signal.market_regime == MarketRegime.HIGH_VOLATILITY:
            tp_multipliers = [1.5, 3.0, 5.0]  # Более широкие цели
            sl_multiplier = 2.0
        elif signal.market_regime == MarketRegime.LOW_VOLATILITY:
            tp_multipliers = [1.0, 2.0, 3.5]  # Более узкие цели
            sl_multiplier = 1.5
        else:
            tp_multipliers = [1.2, 2.5, 4.0]  # Стандартные цели
            sl_multiplier = 1.8

        # Распределение размера позиции по уровням
        size_distribution = [0.5, 0.3, 0.2]  # 50%, 30%, 20%

        if signal.side == OrderSide.BUY:
            # Take Profit уровни
            for i, (tp_mult, size_pct) in enumerate(
                zip(tp_multipliers, size_distribution)
            ):
                tp_price = entry_price + (atr * tp_mult)
                tp_size = position_size * size_pct
                exit_levels.append((tp_price, tp_size, f"TP{i+1}"))

            # Stop Loss
            sl_price = entry_price - (atr * sl_multiplier)
            exit_levels.append((sl_price, position_size, "SL"))

        else:  # SELL
            # Take Profit уровни
            for i, (tp_mult, size_pct) in enumerate(
                zip(tp_multipliers, size_distribution)
            ):
                tp_price = entry_price - (atr * tp_mult)
                tp_size = position_size * size_pct
                exit_levels.append((tp_price, tp_size, f"TP{i+1}"))

            # Stop Loss
            sl_price = entry_price + (atr * sl_multiplier)
            exit_levels.append((sl_price, position_size, "SL"))

        return exit_levels

    async def _check_basic_filters(self, symbol: str, market_conditions: dict) -> bool:
        """Проверка базовых фильтров для торговли"""

        # Проверка торговой сессии
        if market_conditions["trading_session"] == TradingSession.INACTIVE:
            return False

        # Проверка минимальной волатильности
        current_volatility = market_conditions["volatility"]["current"]
        if current_volatility < self.min_volatility_threshold:
            return False

        # Проверка ликвидности
        liquidity_score = market_conditions["liquidity"]["score"]
        if liquidity_score < 0.7:  # Минимальный порог ликвидности
            return False

        # Проверка спреда
        spread_bps = market_conditions["order_book"].get("spread_bps", 999)
        if spread_bps > self.max_spread_bps:
            return False

        # Проверка лимитов позиций
        if len(self.positions) >= self.max_concurrent_positions:
            return False

        # Проверка существующей позиции по символу
        if symbol in self.positions:
            return False

        return True

    def _get_current_trading_session(self) -> TradingSession:
        """
        Определение текущей торговой сессии по UTC времени.

        Классифицирует текущее время в одну из торговых сессий:
        - ASIAN: 00:00-09:00 UTC (Азиатская сессия)
        - EUROPEAN: 07:00-16:00 UTC (Европейская сессия)
        - AMERICAN: 13:00-22:00 UTC (Американская сессия)
        - OVERLAP: Периоды пересечения сессий (максимальная активность)
        - INACTIVE: Остальное время (низкая активность)

        Returns:
            TradingSession: Текущая торговая сессия
        """
        current_hour = datetime.utcnow().hour

        # Проверка перекрытий сессий (наиболее активное время)
        if 7 <= current_hour <= 9:  # EUR-ASIA overlap
            return TradingSession.OVERLAP
        elif 13 <= current_hour <= 16:  # EUR-USA overlap
            return TradingSession.OVERLAP
        elif 0 <= current_hour <= 9:  # Asian session
            return TradingSession.ASIAN
        elif 7 <= current_hour <= 16:  # European session
            return TradingSession.EUROPEAN
        elif 13 <= current_hour <= 22:  # American session
            return TradingSession.AMERICAN
        else:
            return TradingSession.INACTIVE

    def _get_regime_multiplier(self, regime: MarketRegime) -> float:
        """
        Получение мультипликатора размера позиции для рыночного режима.

        Корректирует размер позиции в зависимости от текущего режима рынка:
        - TRENDING: 1.2 (увеличиваем на трендах)
        - RANGING: 0.8 (уменьшаем во флэте)
        - HIGH_VOLATILITY: 0.7 (осторожность при высокой волатильности)
        - LOW_VOLATILITY: 1.1 (немного больше при низкой волатильности)
        - NEWS_EVENT: 0.5 (минимальный размер при новостях)

        Args:
            regime: Текущий рыночный режим

        Returns:
            float: Мультипликатор для размера позиции (0.5 - 1.2)
        """
        multipliers = {
            MarketRegime.TRENDING: 1.2,  # Увеличиваем размер на трендах
            MarketRegime.RANGING: 0.8,  # Уменьшаем в боковике
            MarketRegime.HIGH_VOLATILITY: 0.7,  # Осторожность при высокой волатильности
            MarketRegime.LOW_VOLATILITY: 1.1,  # Немного больше при низкой волатильности
            MarketRegime.NEWS_EVENT: 0.5,  # Минимальный размер при новостях
        }
        return multipliers.get(regime, 1.0)

    async def update_performance_stats(self, closed_position: Position):
        """Обновление статистики производительности после закрытия позиции"""

        pnl = closed_position.realized_pnl
        self.trade_history.append(pnl)

        # Ограничение истории для оптимизации памяти
        if len(self.trade_history) > 1000:
            self.trade_history = self.trade_history[-500:]  # Оставляем последние 500

        # Обновление основных метрик
        self.performance_stats["total_trades"] += 1
        if pnl > 0:
            self.performance_stats["winning_trades"] += 1

        self.performance_stats["total_pnl"] += pnl

        # Расчет производных метрик
        total_trades = self.performance_stats["total_trades"]
        if total_trades > 0:
            self.performance_stats["win_rate"] = (
                self.performance_stats["winning_trades"] / total_trades
            )

        # Пересчет Kelly fraction каждые N сделок
        if total_trades % self.kelly_calculation_period == 0:
            self._calculate_kelly_fraction()

        # Расчет Sharpe ratio (упрощенный)
        if len(self.trade_history) >= 30:
            returns = np.array(self.trade_history[-30:])  # Последние 30 сделок
            if np.std(returns) > 0:
                self.performance_stats["sharpe_ratio"] = np.mean(returns) / np.std(
                    returns
                )

    async def emergency_shutdown(self):
        """Экстренное закрытие всех позиций"""
        logger.warning("Emergency shutdown initiated")

        try:
            # Отмена всех pending ордеров
            for order_id in list(self.pending_orders.keys()):
                try:
                    await self.client.cancel_order(order_id)
                except Exception as e:
                    logger.error(f"Failed to cancel order {order_id}: {e}")

            # Закрытие всех позиций по рынку
            for symbol, position in list(self.positions.items()):
                try:
                    await self._close_position_market(symbol, "emergency")
                except Exception as e:
                    logger.error(f"Failed to close position {symbol}: {e}")

            # Остановка стратегии
            self.active = False

            logger.info("Emergency shutdown completed")

        except Exception as e:
            logger.critical(f"Critical error during emergency shutdown: {e}")

    async def _close_position_market(self, symbol: str, reason: str) -> None:
        """
        Закрытие позиции по рыночной цене с немедленным исполнением.

        Размещает рыночный ордер для немедленного закрытия позиции,
        обновляет статистику производительности и удаляет позицию из трекинга.

        Args:
            symbol: Торговый символ
            reason: Причина закрытия (emergency, stop_loss, take_profit, etc.)

        Raises:
            Exception: При ошибках размещения ордера
        """
        position = self.positions.get(symbol)
        if not position:
            return

        # Определение направления ордера (противоположного позиции)
        order_side = OrderSide.SELL if position.side == "long" else OrderSide.BUY

        # Размещение рыночного ордера
        order = await self.client.place_order(
            symbol=symbol,
            side=order_side,
            order_type=OrderType.MARKET,
            amount=position.size,
        )

        if order:
            logger.info(
                f"Position {symbol} closed by {reason}, PnL: {position.unrealized_pnl:.4f}"
            )
            await self.update_performance_stats(position)
            del self.positions[symbol]

    def get_detailed_performance_report(self) -> dict:
        """Получение детального отчета о производительности"""

        if not self.trade_history:
            return {"error": "No trade history available"}

        trades = np.array(self.trade_history)
        wins = trades[trades > 0]
        losses = trades[trades < 0]

        report = {
            "strategy_id": self.strategy_id,
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(trades) * 100 if len(trades) > 0 else 0,
            "total_pnl": float(np.sum(trades)),
            "avg_win": float(np.mean(wins)) if len(wins) > 0 else 0,
            "avg_loss": float(np.mean(losses)) if len(losses) > 0 else 0,
            "best_trade": float(np.max(trades)),
            "worst_trade": float(np.min(trades)),
            "profit_factor": abs(np.sum(wins) / np.sum(losses))
            if len(losses) > 0
            else float("inf"),
            "sharpe_ratio": self.performance_stats.get("sharpe_ratio", 0),
            "kelly_fraction": self.performance_stats.get("kelly_fraction", 0.25),
            "max_consecutive_wins": self._calculate_max_consecutive(
                trades, positive=True
            ),
            "max_consecutive_losses": self._calculate_max_consecutive(
                trades, positive=False
            ),
            "current_drawdown": self._calculate_current_drawdown(trades),
            "max_drawdown": self._calculate_max_drawdown(trades),
        }

        return report

    def _calculate_max_consecutive(
        self, trades: np.ndarray, positive: bool = True
    ) -> int:
        """
        Расчет максимального количества последовательных выигрышей/проигрышей.

        Анализирует историю сделок и находит самую длинную серию
        последовательных положительных или отрицательных результатов.

        Args:
            trades: Массив результатов сделок (положительные = прибыль)
            positive: True для выигрышей, False для проигрышей

        Returns:
            int: Максимальное количество последовательных сделок
        """
        if len(trades) == 0:
            return 0

        max_consecutive = 0
        current_consecutive = 0

        for trade in trades:
            if (positive and trade > 0) or (not positive and trade < 0):
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0

        return max_consecutive

    def _calculate_current_drawdown(self, trades: np.ndarray) -> float:
        """
        Расчет текущей просадки (разница между пиком и текущим значением).

        Вычисляет насколько текущий баланс ниже максимального достигнутого
        значения за всю историю торговли.

        Args:
            trades: Массив результатов всех сделок

        Returns:
            float: Текущая просадка (отрицательное число или 0)
        """
        if len(trades) == 0:
            return 0.0

        cumulative = np.cumsum(trades)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max

        return float(drawdown[-1])

    def _calculate_max_drawdown(self, trades: np.ndarray) -> float:
        """
        Расчет максимальной просадки за всю историю торговли.

        Находит самую большую просадку (падение от пика) за всё время.
        Это ключевая метрика риска, показывающая худший сценарий
        для баланса счёта.

        Args:
            trades: Массив результатов всех сделок

        Returns:
            float: Максимальная просадка (отрицательное число или 0)
        """
        if len(trades) == 0:
            return 0.0

        cumulative = np.cumsum(trades)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max

        return float(np.min(drawdown))
