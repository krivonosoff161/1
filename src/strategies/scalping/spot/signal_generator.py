"""
Генератор торговых сигналов для скальпинг стратегии.

Ответственность:
- Расчет long/short score (0-12 баллов)
- Интеграция с Phase 1 модулями (MTF, Correlation, Pivot, VP)
- ARM обновление режима
- Фильтры (min_volatility, существующие позиции)
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from src.indicators import IndicatorManager
from src.models import OHLCV, OrderSide, Position, Signal


class SignalGenerator:
    """
    Генератор торговых сигналов.

    Использует scoring систему (0-12 баллов) для определения силы сигнала.
    """

    def __init__(
        self,
        client,
        config,
        risk_config,
        modules: Dict,
        indicators_manager: IndicatorManager,
    ):
        """
        Args:
            client: OKX клиент
            config: Scalping конфигурация
            risk_config: Risk конфигурация
            modules: Словарь Phase 1 модулей (mtf, correlation, pivot, vp, arm, balance)
            indicators_manager: Менеджер индикаторов
        """
        self.client = client
        self.config = config
        self.risk_config = risk_config
        self.indicators_manager = indicators_manager

        # Phase 1 модули
        # Сохраняем ссылку на все модули
        self.modules = modules

        # Извлекаем конкретные модули для удобства
        self.mtf_filter = modules.get("mtf")
        self.correlation_filter = modules.get("correlation")
        self.pivot_filter = modules.get("pivot")
        self.volume_profile_filter = modules.get("vp")
        self.balance_checker = modules.get("balance")
        self.adaptive_regime = modules.get("arm")
        self.time_filter = modules.get("time")

        # Состояние
        self.scoring_enabled = True
        self.strategy_id = "scalping_modular_v2"

        # ARM параметры
        self.current_regime_type = None
        self.current_indicator_params = None
        self.current_module_params = None
        self.min_score_threshold = 3  # Дефолтный порог

        # Для детального логирования (раз в 30 сек)
        self._last_detail_log = {}

        logger.info("✅ SignalGenerator initialized")

    async def generate_signal(
        self,
        symbol: str,
        indicators: Dict,
        tick,
        current_positions: Dict[str, Position],
        market_data=None,  # 🆕 Для ADX фильтра
    ) -> Optional[Signal]:
        """
        Генерация торгового сигнала через scoring систему.

        Args:
            symbol: Торговый символ
            indicators: Рассчитанные индикаторы
            tick: Текущий тик
            current_positions: Текущие открытые позиции
            market_data: Рыночные данные (для ADX)

        Returns:
            Signal или None
        """

        # 🔥 КРИТИЧНЫЙ ФИКС #1: Блокируем множественные позиции!
        if symbol in current_positions:
            logger.debug(f"🚫 {symbol}: Position already open - skipping signal")
            return None

        # Извлекаем индикаторы
        sma_fast = indicators.get("SMA_FAST")
        sma_slow = indicators.get("SMA_SLOW")
        ema_fast = indicators.get("EMA_FAST")
        ema_slow = indicators.get("EMA_SLOW")
        rsi = indicators.get("RSI")
        atr = indicators.get("ATR")
        bb = indicators.get("BB")
        volume = indicators.get("VOLUME")
        macd = indicators.get("MACD")

        # Проверка наличия всех индикаторов
        required_indicators = [
            sma_fast,
            sma_slow,
            ema_fast,
            ema_slow,
            rsi,
            atr,
            bb,
            volume,
            macd,
        ]
        if not all(required_indicators):
            missing = []
            if not sma_fast:
                missing.append("SMA_FAST")
            if not sma_slow:
                missing.append("SMA_SLOW")
            if not ema_fast:
                missing.append("EMA_FAST")
            if not ema_slow:
                missing.append("EMA_SLOW")
            if not rsi:
                missing.append("RSI")
            if not atr:
                missing.append("ATR")
            if not bb:
                missing.append("BB")
            if not volume:
                missing.append("VOLUME")
            if not macd:
                missing.append("MACD")
            logger.debug(f"🚫 {symbol}: Missing indicators: {', '.join(missing)}")
            return None

        current_price = tick.price

        # Проверка минимальной волатильности
        min_volatility = self.config.entry.min_volatility_atr
        if self.current_indicator_params:
            min_volatility = self.current_indicator_params.min_volatility_atr

        if atr.value < min_volatility:
            if atr.value == 0.0:
                error_info = atr.metadata.get("error", "Unknown reason")
                logger.warning(f"🚫 {symbol}: ATR is ZERO! {error_info}")
            else:
                logger.debug(
                    f"🚫 {symbol}: Low volatility: ATR={atr.value:.6f} (min={min_volatility})"
                )
            return None

        # 📊 SCORING СИСТЕМА
        long_score = 0
        short_score = 0

        # Получаем динамические параметры RSI и Volume из ARM
        rsi_oversold = (
            self.current_indicator_params.rsi_oversold
            if self.current_indicator_params
            else self.config.entry.rsi_oversold
        )
        rsi_overbought = (
            self.current_indicator_params.rsi_overbought
            if self.current_indicator_params
            else self.config.entry.rsi_overbought
        )
        volume_threshold = (
            self.current_indicator_params.volume_threshold
            if self.current_indicator_params
            else self.config.entry.volume_threshold
        )

        # === LONG SCORING ===

        # SMA Trend (+1 балл)
        long_score += 1 if (current_price > sma_fast.value > sma_slow.value) else 0

        # EMA Trend (+2 балла)
        long_score += 2 if ema_fast.value > ema_slow.value else 0

        # RSI - зональная логика (+1 до +4 баллов)
        if rsi.value <= (rsi_oversold - 5):  # Extreme
            long_score += 4
        elif rsi.value <= rsi_oversold:  # Strong
            long_score += 3
        elif rsi.value <= (rsi_oversold + 10):  # Weak
            long_score += 2
        elif rsi.value <= (rsi_oversold + 20):  # Neutral-bullish
            long_score += 1

        # Bollinger Bands (+2 балла)
        long_score += 2 if current_price <= bb.metadata["lower_band"] * 1.002 else 0

        # Volume (+2 балла)
        long_score += 2 if volume.value >= volume_threshold else 0

        # MACD (+2 балла)
        macd_line = macd.metadata.get("macd_line", 0)
        macd_signal = macd.metadata.get("signal_line", 0)
        long_score += 2 if (macd_line > macd_signal and macd_line > 0) else 0

        # === SHORT SCORING ===

        # SMA Trend (+1 балл)
        short_score += 1 if (current_price < sma_fast.value < sma_slow.value) else 0

        # EMA Trend (+2 балла)
        short_score += 2 if ema_fast.value < ema_slow.value else 0

        # RSI - зональная логика (+1 до +4 баллов)
        if rsi.value >= (rsi_overbought + 5):  # Extreme
            short_score += 4
        elif rsi.value >= rsi_overbought:  # Strong
            short_score += 3
        elif rsi.value >= (rsi_overbought - 10):  # Weak
            short_score += 2
        elif rsi.value >= (rsi_overbought - 20):  # Neutral-bearish
            short_score += 1

        # Bollinger Bands (+2 балла)
        short_score += 2 if current_price >= bb.metadata["upper_band"] * 0.998 else 0

        # Volume (+2 балла)
        short_score += 2 if volume.value >= volume_threshold else 0

        # MACD (+2 балла)
        short_score += 2 if (macd_line < macd_signal and macd_line < 0) else 0

        # Расчет confidence
        long_confidence = long_score / 12.0
        short_confidence = short_score / 12.0

        # 🔍 ВСЕГДА логируем детальный scoring (для 2-часового теста)
        logger.debug(
            f"📊 {symbol} SCORING DETAILS:\n"
            f"  LONG: {long_score}/12\n"
            f"    SMA: +{1 if (current_price > sma_fast.value > sma_slow.value) else 0} "
            f"(Price: ${current_price:.2f} > Fast: ${sma_fast.value:.2f} > Slow: ${sma_slow.value:.2f})\n"
            f"    EMA: +{2 if ema_fast.value > ema_slow.value else 0} "
            f"(Fast: ${ema_fast.value:.2f} > Slow: ${ema_slow.value:.2f})\n"
            f"    RSI: +{self._calc_rsi_score_long(rsi.value, rsi_oversold)} "
            f"(Value: {rsi.value:.1f}, Oversold: {rsi_oversold})\n"
            f"    BB: +{2 if current_price <= bb.metadata['lower_band'] * 1.002 else 0} "
            f"(Price: ${current_price:.2f} vs Lower: ${bb.metadata['lower_band']:.2f})\n"
            f"    Vol: +{2 if volume.value >= volume_threshold else 0} "
            f"(Ratio: {volume.value:.2f}, Threshold: {volume_threshold})\n"
            f"    MACD: +{2 if (macd.metadata.get('macd_line', 0) > macd.metadata.get('signal_line', 0) and macd.metadata.get('macd_line', 0) > 0) else 0}\n"
            f"  SHORT: {short_score}/12\n"
            f"    SMA: +{1 if (current_price < sma_fast.value < sma_slow.value) else 0}\n"
            f"    EMA: +{2 if ema_fast.value < ema_slow.value else 0}\n"
            f"    RSI: +{self._calc_rsi_score_short(rsi.value, rsi_overbought)}\n"
            f"    BB: +{2 if current_price >= bb.metadata['upper_band'] * 0.998 else 0}\n"
            f"    Vol: +{2 if volume.value >= volume_threshold else 0}\n"
            f"    MACD: +{2 if (macd.metadata.get('macd_line', 0) < macd.metadata.get('signal_line', 0) and macd.metadata.get('macd_line', 0) < 0) else 0}"
        )

        # ARM - получаем текущий порог score
        current_score_threshold = await self._get_score_threshold(symbol, current_price)

        # PHASE 1: Time-Based Filter
        if self.time_filter:
            if not self.time_filter.is_trading_allowed():
                next_time = self.time_filter.get_next_trading_time()
                logger.info(
                    f"⏰ TIME FILTER BLOCKED: {symbol} | "
                    f"Reason: Outside trading hours | {next_time}"
                )
                return None

        # PHASE 1: Correlation Filter
        signal_direction = None
        if long_score >= current_score_threshold and long_score > short_score:
            signal_direction = "LONG"
        elif short_score >= current_score_threshold and short_score > long_score:
            signal_direction = "SHORT"

        if signal_direction and self.correlation_filter:
            corr_result = await self.correlation_filter.check_entry(
                symbol, signal_direction, current_positions
            )
            if corr_result.blocked:
                logger.warning(
                    f"🚫 CORRELATION BLOCKED: {symbol} {signal_direction} | "
                    f"Reason: {corr_result.reason} | "
                    f"Correlated: {corr_result.correlated_positions}"
                )
                return None

        # PHASE 1: Volume Profile (общий бонус)
        if self.volume_profile_filter:
            vp_result = await self.volume_profile_filter.check_entry(
                symbol, current_price
            )
            if vp_result.bonus > 0:
                vp_multiplier = self._get_vp_multiplier()
                adjusted_bonus = int(round(vp_result.bonus * vp_multiplier))

                if signal_direction == "LONG":
                    long_score += adjusted_bonus
                    long_confidence = long_score / 12.0
                    logger.info(
                        f"✅ VOLUME PROFILE BONUS: {symbol} LONG | "
                        f"Reason: {vp_result.reason} | Bonus: +{adjusted_bonus} | "
                        f"New score: {long_score}/12"
                    )
                elif signal_direction == "SHORT":
                    short_score += adjusted_bonus
                    short_confidence = short_score / 12.0
                    logger.info(
                        f"✅ VOLUME PROFILE BONUS: {symbol} SHORT | "
                        f"Reason: {vp_result.reason} | Bonus: +{adjusted_bonus} | "
                        f"New score: {short_score}/12"
                    )

        # PHASE 1: Pivot Points
        if self.pivot_filter and signal_direction:
            pivot_result = await self.pivot_filter.check_entry(
                symbol, current_price, signal_direction
            )
            if pivot_result.near_level and pivot_result.bonus > 0:
                pivot_multiplier = self._get_pivot_multiplier()
                adjusted_bonus = int(round(pivot_result.bonus * pivot_multiplier))

                if signal_direction == "LONG":
                    long_score += adjusted_bonus
                    long_confidence = long_score / 12.0
                    logger.info(
                        f"✅ PIVOT BONUS: {symbol} LONG near {pivot_result.level_name} | "
                        f"Bonus: +{adjusted_bonus} | New score: {long_score}/12"
                    )
                elif signal_direction == "SHORT":
                    short_score += adjusted_bonus
                    short_confidence = short_score / 12.0
                    logger.info(
                        f"✅ PIVOT BONUS: {symbol} SHORT near {pivot_result.level_name} | "
                        f"Bonus: +{adjusted_bonus} | New score: {short_score}/12"
                    )

        # PHASE 1: Multi-Timeframe Confirmation
        if self.mtf_filter and signal_direction:
            mtf_result = await self.mtf_filter.check_confirmation(
                symbol, signal_direction
            )

            if mtf_result.blocked:
                logger.warning(
                    f"🚫 MTF BLOCKED: {symbol} {signal_direction} | "
                    f"Reason: {mtf_result.reason}"
                )
                return None

            if mtf_result.confirmed:
                if signal_direction == "LONG":
                    long_score += mtf_result.bonus
                    long_confidence = long_score / 12.0
                    logger.info(
                        f"✅ MTF CONFIRMED: {symbol} LONG | "
                        f"Bonus: +{mtf_result.bonus} | New score: {long_score}/12"
                    )
                elif signal_direction == "SHORT":
                    short_score += mtf_result.bonus
                    short_confidence = short_score / 12.0
                    logger.info(
                        f"✅ MTF CONFIRMED: {symbol} SHORT | "
                        f"Bonus: +{mtf_result.bonus} | New score: {short_score}/12"
                    )

        # 🆕 PHASE 2: ADX Filter (сила тренда)
        if self.modules.get("adx") and signal_direction and market_data:
            # Получаем свечи для ADX (используем основной таймфрейм)
            candles = market_data.ohlcv_data[-50:]  # Последние 50 свечей

            # Определяем side для проверки
            side = OrderSide.BUY if signal_direction == "LONG" else OrderSide.SELL

            # Проверяем ADX
            adx_result = self.modules["adx"].check_trend_strength(symbol, side, candles)

            if not adx_result.allowed:
                logger.warning(
                    f"🚫 ADX BLOCKED: {symbol} {signal_direction} | "
                    f"Reason: {adx_result.reason}"
                )
                return None

            logger.info(
                f"✅ ADX CONFIRMED: {symbol} {signal_direction} | "
                f"{adx_result.reason}"
            )

        # Логируем итоговый скоринг
        logger.info(
            f"📊 {symbol} FINAL SCORING: LONG {long_score}/12 ({long_confidence:.1%}) | "
            f"SHORT {short_score}/12 ({short_confidence:.1%}) | "
            f"Threshold: {current_score_threshold}/12"
        )

        # Генерация сигнала
        if long_score >= current_score_threshold and long_score > short_score:
            logger.info(
                f"🎯 SIGNAL GENERATED: {symbol} LONG | "
                f"Score: {long_score}/12 | Confidence: {long_confidence:.1%} | "
                f"Price: ${current_price:,.2f}"
            )
            # Сохраняем indicators в dict (только значения)
            indicators_dict = {k: v.value for k, v in indicators.items()}

            logger.debug(f"📊 LONG Signal indicators: {list(indicators_dict.keys())}")

            return Signal(
                symbol=symbol,
                side=OrderSide.BUY,
                strength=long_confidence,
                price=current_price,
                timestamp=datetime.utcnow(),
                strategy_id=self.strategy_id,
                indicators=indicators_dict,
                confidence=long_confidence,
            )

        elif short_score >= current_score_threshold and short_score > long_score:
            logger.info(
                f"🎯 SIGNAL GENERATED: {symbol} SHORT | "
                f"Score: {short_score}/12 | Confidence: {short_confidence:.1%} | "
                f"Price: ${current_price:,.2f}"
            )
            # Сохраняем indicators в dict (только значения)
            indicators_dict = {k: v.value for k, v in indicators.items()}

            logger.debug(f"📊 SHORT Signal indicators: {list(indicators_dict.keys())}")

            return Signal(
                symbol=symbol,
                side=OrderSide.SELL,
                strength=short_confidence,
                price=current_price,
                timestamp=datetime.utcnow(),
                strategy_id=self.strategy_id,
                indicators=indicators_dict,
                confidence=short_confidence,
            )

        # Нет сигнала - логируем почему
        if (
            long_score < current_score_threshold
            and short_score < current_score_threshold
        ):
            logger.debug(
                f"⚪ {symbol} No signal: Both scores too low "
                f"(L:{long_score}/12, S:{short_score}/12, need {current_score_threshold})"
            )
        elif long_score == short_score:
            logger.debug(
                f"⚪ {symbol} No signal: Equal scores "
                f"(L:{long_score}/12, S:{short_score}/12)"
            )

        return None

    async def _get_score_threshold(self, symbol: str, current_price: float) -> int:
        """
        Получить текущий порог score с учетом ARM.

        Returns:
            int: Минимальный score для генерации сигнала
        """
        current_score_threshold = self.min_score_threshold

        if self.adaptive_regime:
            # ARM обновляет режим рынка
            # Получаем параметры для текущего режима
            regime_params = self.adaptive_regime.get_current_parameters()
            current_score_threshold = regime_params.min_score_threshold

            logger.debug(
                f"🧠 Market Regime: {self.adaptive_regime.current_regime.value.upper()} | "
                f"Threshold: {current_score_threshold}/12"
            )

        return current_score_threshold

    def _get_vp_multiplier(self) -> float:
        """Получить Volume Profile bonus multiplier из ARM"""
        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            return regime_params.volume_profile_bonus_multiplier
        return 1.0

    def _get_pivot_multiplier(self) -> float:
        """Получить Pivot Points bonus multiplier из ARM"""
        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            return regime_params.pivot_bonus_multiplier
        return 1.0

    async def _log_scoring_details(
        self,
        symbol: str,
        long_score: int,
        short_score: int,
        current_price: float,
        sma_fast,
        sma_slow,
        ema_fast,
        ema_slow,
        rsi,
        bb,
        volume,
        macd,
        rsi_oversold: float,
        rsi_overbought: float,
        volume_threshold: float,
    ):
        """Детальное логирование scoring (каждые 30 секунд)"""
        current_time = datetime.utcnow()

        last_log = self._last_detail_log.get(symbol, current_time)
        if (current_time - last_log).total_seconds() < 30:
            return

        macd_line = macd.metadata.get("macd_line", 0)
        macd_signal_line = macd.metadata.get("signal_line", 0)

        logger.info(
            f"📊 {symbol} SCORING DETAILS:\n"
            f"  LONG: {long_score}/12\n"
            f"    SMA: +{1 if (current_price > sma_fast.value > sma_slow.value) else 0}\n"
            f"    EMA: +{2 if ema_fast.value > ema_slow.value else 0}\n"
            f"    RSI: +{self._calc_rsi_score_long(rsi.value, rsi_oversold)}\n"
            f"    BB: +{2 if current_price <= bb.metadata.get('lower_band', 0) * 1.002 else 0}\n"
            f"    Vol: +{2 if volume.value >= volume_threshold else 0}\n"
            f"    MACD: +{2 if (macd_line > macd_signal_line and macd_line > 0) else 0}\n"
            f"  SHORT: {short_score}/12\n"
            f"    SMA: +{1 if (current_price < sma_fast.value < sma_slow.value) else 0}\n"
            f"    EMA: +{2 if ema_fast.value < ema_slow.value else 0}\n"
            f"    RSI: +{self._calc_rsi_score_short(rsi.value, rsi_overbought)}\n"
            f"    BB: +{2 if current_price >= bb.metadata.get('upper_band', 0) * 0.998 else 0}\n"
            f"    Vol: +{2 if volume.value >= volume_threshold else 0}\n"
            f"    MACD: +{2 if (macd_line < macd_signal_line and macd_line < 0) else 0}"
        )

        self._last_detail_log[symbol] = current_time

    def _calc_rsi_score_long(self, rsi_value: float, oversold: float) -> int:
        """Расчет RSI score для LONG"""
        if rsi_value <= (oversold - 5):
            return 4
        elif rsi_value <= oversold:
            return 3
        elif rsi_value <= (oversold + 10):
            return 2
        elif rsi_value <= (oversold + 20):
            return 1
        return 0

    def _calc_rsi_score_short(self, rsi_value: float, overbought: float) -> int:
        """Расчет RSI score для SHORT"""
        if rsi_value >= (overbought + 5):
            return 4
        elif rsi_value >= overbought:
            return 3
        elif rsi_value >= (overbought - 10):
            return 2
        elif rsi_value >= (overbought - 20):
            return 1
        return 0

    async def update_regime_parameters(
        self, candles: List[OHLCV], current_price: float
    ):
        """
        Обновление режима через ARM.

        Вызывается из Orchestrator перед генерацией сигнала.
        """
        if not self.adaptive_regime:
            return

        new_regime = self.adaptive_regime.update_regime(candles, current_price)

        if new_regime and new_regime != self.current_regime_type:
            logger.info(f"🔄 Regime changed: {self.current_regime_type} → {new_regime}")
            self.current_regime_type = new_regime

            # Обновляем параметры
            regime_params = self.adaptive_regime.get_current_parameters()
            self.current_indicator_params = regime_params.indicators
            self.current_module_params = regime_params.modules
            self.min_score_threshold = regime_params.min_score_threshold

            # 🔥 КРИТИЧНО: Обновляем параметры МОДУЛЕЙ!
            self._update_module_parameters(regime_params.modules)

            logger.info(
                f"✅ Parameters updated for {new_regime.value.upper()} regime:\n"
                f"  Score threshold: {regime_params.min_score_threshold}/12\n"
                f"  TP multiplier: {regime_params.tp_atr_multiplier}x\n"
                f"  SL multiplier: {regime_params.sl_atr_multiplier}x\n"
                f"  Max holding: {regime_params.max_holding_minutes} min\n"
                f"  Position size: {regime_params.position_size_multiplier}x"
            )
        elif not self.current_regime_type:
            # 🔍 ПЕРВЫЙ ЗАПУСК: Логируем начальный режим ДЕТАЛЬНО
            self.current_regime_type = self.adaptive_regime.current_regime
            regime_params = self.adaptive_regime.get_current_parameters()

            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(
                f"🎯 ARM НАЧАЛЬНЫЙ РЕЖИМ: {self.current_regime_type.value.upper()}"
            )
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"  Score threshold: {regime_params.min_score_threshold}/12")
            logger.info(
                f"  TP/SL: {regime_params.tp_atr_multiplier}/{regime_params.sl_atr_multiplier} ATR"
            )
            logger.info(f"  Max holding: {regime_params.max_holding_minutes} min")
            logger.info(f"  Position size: {regime_params.position_size_multiplier}x")
            logger.info("")
            logger.info(f"  📊 ИНДИКАТОРЫ:")
            logger.info(
                f"     Volume threshold: {regime_params.indicators.volume_threshold}"
            )
            logger.info(
                f"     RSI boundaries: {regime_params.indicators.rsi_oversold}-{regime_params.indicators.rsi_overbought}"
            )
            logger.info("")
            logger.info(f"  ✨ PROFIT HARVESTING:")
            logger.info(f"     Enabled: {'YES' if regime_params.ph_enabled else 'NO'}")
            logger.info(f"     Threshold: ${regime_params.ph_threshold:.2f}")
            logger.info(
                f"     Time Limit: {regime_params.ph_time_limit}s ({regime_params.ph_time_limit/60:.1f} min)"
            )
            logger.info("")
            logger.info(f"  🔧 МОДУЛИ:")
            logger.info(
                f"     MTF block_opposite: {regime_params.modules.mtf_block_opposite}"
            )
            logger.info(
                f"     MTF score_bonus: {regime_params.modules.mtf_score_bonus}"
            )
            logger.info(
                f"     Correlation threshold: {regime_params.modules.correlation_threshold}"
            )
            logger.info(
                f"     Correlation max_positions: {regime_params.modules.max_correlated_positions}"
            )
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def _update_module_parameters(self, module_params):
        """
        Обновить параметры модулей Phase 1 при переключении режима ARM.

        Args:
            module_params: ModuleParameters из ARM
        """
        from src.strategies.modules.correlation_filter import \
            CorrelationFilterConfig
        from src.strategies.modules.multi_timeframe import MTFConfig

        logger.info("🔧 Обновление параметров модулей...")

        # 1. Multi-Timeframe
        if self.mtf_filter:
            mtf_config = MTFConfig(
                enabled=True,
                confirmation_timeframe=module_params.mtf_confirmation_timeframe,
                score_bonus=module_params.mtf_score_bonus,
                block_opposite=module_params.mtf_block_opposite,
                ema_fast_period=8,
                ema_slow_period=21,
            )
            self.mtf_filter.update_parameters(mtf_config)

        # 2. Correlation Filter
        if self.correlation_filter:
            corr_config = CorrelationFilterConfig(
                enabled=True,
                correlation_threshold=module_params.correlation_threshold,
                max_correlated_positions=module_params.max_correlated_positions,
                block_same_direction_only=module_params.block_same_direction_only,
            )
            self.correlation_filter.update_parameters(corr_config)

        # 3. 🆕 ADX Filter
        if self.modules.get("adx"):
            from src.strategies.modules.adx_filter import ADXFilterConfig

            adx_config = ADXFilterConfig(
                enabled=True,
                adx_threshold=module_params.adx_threshold,
                di_difference=module_params.adx_di_difference,
                adx_period=14,  # Фиксированный период
                timeframe="15m",  # Фиксированный таймфрейм
            )
            self.modules["adx"].update_parameters(adx_config)

        logger.info("✅ Модули обновлены!")
