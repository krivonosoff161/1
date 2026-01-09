"""
Trend Following Signal Generator - генерация LONG сигналов в uptrend.

Решает проблему отсутствия LONG позиций в trending рынках, где:
- RSI редко опускается ниже 30 (oversold)
- MACD уже в bullish зоне без новых пересечений

Стратегия:
- Pullback к EMA в uptrend → LONG entry
- Breakout выше локального максимума → LONG continuation
- Поддержка на уровне → LONG bounce
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from src.models import MarketData


class TrendFollowingSignalGenerator:
    """
    Генератор сигналов для следования за трендом.

    Основные стратегии:
    1. **Pullback Entry:** Цена откатывает к EMA в uptrend → LONG
    2. **Breakout Entry:** Пробой локального максимума → LONG
    3. **Support Bounce:** Отскок от уровня поддержки → LONG

    Все сигналы генерируются только при подтвержденном uptrend:
    - EMA Fast > EMA Slow
    - Price выше обеих EMA
    - ADX > 20 (опционально)
    """

    def __init__(
        self,
        regime_managers: Dict[str, Any] = None,
        regime_manager: Any = None,
        get_current_market_price_callback=None,
        get_regime_indicators_params_callback=None,
        scalping_config=None,
    ):
        """
        Инициализация TrendFollowingSignalGenerator.

        Args:
            regime_managers: Словарь менеджеров режимов по символам
            regime_manager: Общий менеджер режимов
            get_current_market_price_callback: Callback для получения текущей цены
            get_regime_indicators_params_callback: Callback для получения параметров индикаторов
            scalping_config: Конфигурация скальпинга
        """
        self.regime_managers = regime_managers or {}
        self.regime_manager = regime_manager
        self.get_current_market_price_callback = get_current_market_price_callback
        self.get_regime_indicators_params_callback = (
            get_regime_indicators_params_callback
        )
        self.scalping_config = scalping_config

    async def generate_signals(
        self,
        symbol: str,
        indicators: Dict,
        market_data: MarketData,
        adx_trend: Optional[str] = None,
        adx_value: float = 0.0,
        adx_threshold: float = 20.0,
    ) -> List[Dict[str, Any]]:
        """
        Генерация Trend Following сигналов.

        Args:
            symbol: Торговый символ
            indicators: Словарь индикаторов
            market_data: Рыночные данные
            adx_trend: Тренд ADX (bullish/bearish/neutral)
            adx_value: Значение ADX
            adx_threshold: Порог ADX для подтверждения тренда

        Returns:
            Список сигналов
        """
        signals = []

        try:
            # Получаем индикаторы
            ema_fast = indicators.get("ema_12", 0)
            ema_slow = indicators.get("ema_26", 0)
            sma_fast = indicators.get("sma_20", 0)

            # Получаем свечи
            if not market_data.ohlcv_data or len(market_data.ohlcv_data) < 20:
                return []

            candles = market_data.ohlcv_data
            current_candle = candles[-1]
            prev_candle = candles[-2] if len(candles) > 1 else None

            # Получаем актуальную цену
            candle_close_price = current_candle.close
            current_price = candle_close_price
            if self.get_current_market_price_callback:
                current_price = await self.get_current_market_price_callback(
                    symbol, candle_close_price
                )

            # Получаем режим
            regime_manager = self.regime_managers.get(symbol) or self.regime_manager
            current_regime = (
                regime_manager.get_current_regime() if regime_manager else "ranging"
            )

            # Получаем confidence из конфига
            regime_name = current_regime if current_regime else "ranging"
            if isinstance(regime_name, str):
                regime_name = regime_name.lower()
            else:
                regime_name = str(regime_name).lower()

            confidence_base = 0.70  # Базовый confidence для trend following
            if self.scalping_config:
                signal_gen_config = getattr(
                    self.scalping_config, "signal_generator", {}
                )
                if isinstance(signal_gen_config, dict):
                    confidence_dict = signal_gen_config.get("confidence", {})
                    if regime_name and confidence_dict:
                        regime_confidence = confidence_dict.get(regime_name, {})
                        if isinstance(regime_confidence, dict):
                            confidence_base = regime_confidence.get(
                                "trend_following", 0.70
                            )

            # ✅ ПРОВЕРКА UPTREND (обязательное условие для всех сигналов)
            is_uptrend = (
                ema_fast > ema_slow
                and current_price > ema_fast
                and current_price > ema_slow
            )

            if not is_uptrend:
                # Не генерируем LONG сигналы если нет uptrend
                logger.debug(
                    f"📊 {symbol}: Trend Following пропущен - нет uptrend "
                    f"(ema_fast={ema_fast:.2f}, ema_slow={ema_slow:.2f}, price={current_price:.2f})"
                )
                return []

            # Дополнительная проверка ADX если доступно
            if adx_value > 0 and adx_value < adx_threshold:
                logger.debug(
                    f"📊 {symbol}: Trend Following пропущен - слабый тренд "
                    f"(ADX={adx_value:.1f} < {adx_threshold:.1f})"
                )
                return []

            # ✅ СТРАТЕГИЯ 1: PULLBACK ENTRY (откат к EMA в uptrend)
            # Цена была выше EMA, откатила к EMA или чуть ниже, отскакивает обратно
            pullback_distance_pct = 0.3  # Максимум 0.3% от EMA для pullback
            is_near_ema_fast = (
                ema_fast > 0
                and abs(current_price - ema_fast) / ema_fast * 100
                < pullback_distance_pct
            )

            if is_near_ema_fast and prev_candle:
                # Проверяем что была коррекция (prev цена была ниже current)
                price_recovering = current_price > prev_candle.close

                if price_recovering:
                    confidence = confidence_base + 0.05  # Bonus за pullback

                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",  # LONG
                            "type": "trend_pullback",
                            "price": current_price,
                            "strength": confidence,
                            "confidence": confidence,
                            "reason": (
                                f"Pullback к EMA в uptrend: price={current_price:.2f} "
                                f"near ema_fast={ema_fast:.2f} (distance={abs(current_price - ema_fast) / ema_fast * 100:.2f}% if ema_fast > 0 else 0), "
                                f"recovering from {prev_candle.close:.2f}"
                            ),
                            "timestamp": datetime.now().isoformat(),
                            "regime": current_regime,
                            "indicators": {
                                "ema_fast": ema_fast,
                                "ema_slow": ema_slow,
                                "current_price": current_price,
                                "prev_close": prev_candle.close,
                                "adx": adx_value,
                            },
                        }
                    )

                    logger.info(
                        f"🎯 {symbol}: Trend Pullback LONG сигнал (confidence={confidence:.2f}): "
                        f"price={current_price:.2f} откатила к ema_fast={ema_fast:.2f}, восстанавливается"
                    )

            # ✅ СТРАТЕГИЯ 2: BREAKOUT ENTRY (пробой локального максимума)
            # Цена пробивает максимум последних N свечей
            lookback_candles = min(10, len(candles) - 1)
            if lookback_candles > 0:
                recent_highs = [c.high for c in candles[-lookback_candles:]]
                local_high = max(recent_highs) if recent_highs else 0

                # Пробой если current_price выше локального максимума
                breakout_threshold_pct = 0.05  # Должен быть минимум 0.05% выше
                is_breakout = current_price > local_high * (
                    1 + breakout_threshold_pct / 100
                )

                if is_breakout and prev_candle:
                    # Проверяем что пробой произошел только что (prev была ниже)
                    is_fresh_breakout = prev_candle.close <= local_high

                    if is_fresh_breakout:
                        confidence = confidence_base + 0.08  # Bonus за breakout

                        signals.append(
                            {
                                "symbol": symbol,
                                "side": "buy",  # LONG
                                "type": "trend_breakout",
                                "price": current_price,
                                "strength": confidence,
                                "confidence": confidence,
                                "reason": (
                                    f"Breakout в uptrend: price={current_price:.2f} "
                                    f"пробила local_high={local_high:.2f} "
                                    f"({(current_price - local_high) / local_high * 100:.2f}% выше if local_high > 0 else 0)"
                                ),
                                "timestamp": datetime.now().isoformat(),
                                "regime": current_regime,
                                "indicators": {
                                    "ema_fast": ema_fast,
                                    "ema_slow": ema_slow,
                                    "current_price": current_price,
                                    "local_high": local_high,
                                    "breakout_pct": (current_price - local_high)
                                    / local_high
                                    * 100
                                    if local_high > 0
                                    else 0,
                                    "adx": adx_value,
                                },
                            }
                        )

                        logger.info(
                            f"🎯 {symbol}: Trend Breakout LONG сигнал (confidence={confidence:.2f}): "
                            f"price={current_price:.2f} пробила local_high={local_high:.2f}"
                        )

            # ✅ СТРАТЕГИЯ 3: SUPPORT BOUNCE (отскок от уровня поддержки)
            # Цена касается SMA и отскакивает вверх
            is_near_sma = (
                sma_fast > 0
                and abs(current_price - sma_fast) / sma_fast * 100
                < 0.5  # В пределах 0.5% от SMA
            )

            if is_near_sma and prev_candle and sma_fast > 0:
                # Проверяем что цена отскакивает от SMA (была ниже, стала выше)
                was_below_sma = prev_candle.close < sma_fast
                is_above_sma_now = current_price >= sma_fast

                if was_below_sma and is_above_sma_now:
                    confidence = confidence_base + 0.03  # Bonus за bounce

                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",  # LONG
                            "type": "trend_support_bounce",
                            "price": current_price,
                            "strength": confidence,
                            "confidence": confidence,
                            "reason": (
                                f"Support Bounce в uptrend: price={current_price:.2f} "
                                f"отскочила от sma={sma_fast:.2f} "
                                f"(было {prev_candle.close:.2f} < sma, теперь {current_price:.2f} >= sma)"
                            ),
                            "timestamp": datetime.now().isoformat(),
                            "regime": current_regime,
                            "indicators": {
                                "ema_fast": ema_fast,
                                "ema_slow": ema_slow,
                                "sma_fast": sma_fast,
                                "current_price": current_price,
                                "prev_close": prev_candle.close,
                                "adx": adx_value,
                            },
                        }
                    )

                    logger.info(
                        f"🎯 {symbol}: Trend Support Bounce LONG сигнал (confidence={confidence:.2f}): "
                        f"price={current_price:.2f} отскочила от sma={sma_fast:.2f}"
                    )

            return signals

        except Exception as e:
            logger.error(
                f"❌ Ошибка генерации Trend Following сигналов для {symbol}: {e}",
                exc_info=True,
            )
            return []
