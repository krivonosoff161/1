"""
Trend Following Signal Generator - генерация сигналов в трендовых рынках.

Решает проблему отсутствия позиций в trending рынках, где:
- RSI редко опускается ниже 30 (oversold)
- MACD уже в bullish зоне без новых пересечений

Стратегии:
- Pullback к EMA в uptrend → LONG entry
- Breakout выше локального максимума → LONG continuation
- Поддержка на уровне → LONG bounce
- Trend Dip: резкий intra-candle дип в тренде → вход с трендом (LONG/SHORT)
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

            # Дополнительная проверка ADX если доступно
            if adx_value > 0 and adx_value < adx_threshold:
                logger.debug(
                    f"📊 {symbol}: Trend Following пропущен - слабый тренд "
                    f"(ADX={adx_value:.1f} < {adx_threshold:.1f})"
                )
                return []

            # ✅ TREND DIP сигналы — intra-candle детекция, работает ДО is_uptrend check
            # (потому что во время дипа цена может быть НИЖЕ EMA_fast, что блокирует is_uptrend)
            trend_dip_sigs = self._generate_trend_dip(
                symbol, candles, current_price, indicators, current_regime, adx_value
            )
            signals.extend(trend_dip_sigs)

            # ✅ ПРОВЕРКА UPTREND (обязательное условие для pullback/breakout/bounce)
            is_uptrend = (
                ema_fast > ema_slow
                and current_price > ema_fast
                and current_price > ema_slow
            )

            if not is_uptrend:
                # Не генерируем обычные LONG сигналы если нет uptrend,
                # но trend_dip сигналы уже добавлены выше
                logger.debug(
                    f"📊 {symbol}: Trend Following (pullback/breakout/bounce) пропущен - нет uptrend "
                    f"(ema_fast={ema_fast:.2f}, ema_slow={ema_slow:.2f}, price={current_price:.2f})"
                )
                return signals

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

    def _generate_trend_dip(
        self,
        symbol: str,
        candles: list,
        current_price: float,
        indicators: Dict,
        regime: Any,
        adx_value: float,
    ) -> List[Dict[str, Any]]:
        """
        Детектируем резкую просадку в тренде — вход с трендом (intra-candle скорость).

        Использует ТЕКУЩУЮ незакрытую свечу (candles[-1].high/.low) + WS цену (current_price).
        Это даёт реакцию 1-3 секунды от начала дипа, в отличие от свечного анализа (1+ мин).

        LONG (trend_dip_long):
          - Тренд вверх: EMA_fast > EMA_slow + ADX > min_adx
          - Текущая свеча: high - current_price >= dip_atr_min × ATR
          - current_price < EMA_fast (ещё в зоне просадки, не отскочил)

        SHORT (trend_dip_short):
          - Тренд вниз: EMA_fast < EMA_slow + ADX > min_adx
          - Текущая свеча: current_price - low >= dip_atr_min × ATR
          - current_price > EMA_fast (ещё в зоне шипа)

        Args:
            symbol: Торговый символ
            candles: market_data.ohlcv_data (последний элемент = текущая незакрытая свеча)
            current_price: WS цена в реальном времени
            indicators: Словарь индикаторов (ema_12, ema_26, atr, adx, ...)
            regime: Текущий режим рынка
            adx_value: Значение ADX

        Returns:
            Список сигналов (0 или 1 сигнал)
        """
        # --- Читаем конфиг ---
        td_cfg: Dict[str, Any] = {}
        if self.scalping_config:
            td_raw = self.scalping_config.get("trend_dip", {})
            if hasattr(td_raw, "to_dict"):
                td_cfg = td_raw.to_dict()
            elif isinstance(td_raw, dict):
                td_cfg = td_raw

        if not td_cfg.get("enabled", True):
            return []

        # Только в разрешённых режимах (по умолчанию только trending)
        regimes_enabled = td_cfg.get("regimes_enabled", ["trending"])
        regime_str = str(regime or "").lower()
        if regime_str not in [r.lower() for r in regimes_enabled]:
            return []

        # --- Параметры ---
        min_adx = float(td_cfg.get("min_adx", 22))
        dip_atr_min = float(td_cfg.get("dip_atr_min", 0.4))
        dip_atr_max = float(td_cfg.get("dip_atr_max", 2.5))
        dip_atr_target = float(td_cfg.get("dip_atr_target", 1.2))
        confidence_base = float(td_cfg.get("confidence_base", 0.82))

        # Per-symbol overrides
        by_symbol = td_cfg.get("by_symbol", {})
        if isinstance(by_symbol, dict) and symbol in by_symbol:
            sym_cfg = by_symbol.get(symbol, {})
            if isinstance(sym_cfg, dict):
                dip_atr_min = float(sym_cfg.get("dip_atr_min", dip_atr_min))
                dip_atr_max = float(sym_cfg.get("dip_atr_max", dip_atr_max))
                confidence_base = float(sym_cfg.get("confidence_base", confidence_base))

        # --- Базовые проверки ---
        ema_fast = indicators.get("ema_12", 0) or 0
        ema_slow = indicators.get("ema_26", 0) or 0
        atr = indicators.get("atr", 0) or 0

        if atr <= 0 or ema_fast <= 0 or ema_slow <= 0:
            return []
        if adx_value < min_adx:
            return []
        if len(candles) < 2:
            return []

        current_candle = candles[-1]  # Текущая незакрытая свеча (high/low real-time)
        is_trend_up = ema_fast > ema_slow
        is_trend_down = ema_fast < ema_slow

        # ---- LONG: восходящий тренд + резкий дип вниз ----
        if is_trend_up:
            candle_high = current_candle.high
            if candle_high <= 0 or current_price <= 0:
                return []

            dip_size = (candle_high - current_price) / atr

            if dip_atr_min <= dip_size <= dip_atr_max and current_price < ema_fast:
                strength = min(1.0, dip_size / dip_atr_target) * confidence_base
                sig = {
                    "symbol": symbol,
                    "side": "buy",
                    "type": "trend_dip_long",
                    "price": current_price,
                    "strength": strength,
                    "confidence": confidence_base,
                    "reason": (
                        f"Тренд-дип LONG: дип {dip_size:.2f}×ATR "
                        f"({candle_high:.4f}→{current_price:.4f}), "
                        f"EMA↑({ema_fast:.4f}>{ema_slow:.4f}), ADX={adx_value:.1f}"
                    ),
                    "timestamp": datetime.now().isoformat(),
                    "regime": regime_str,
                    "indicators": {
                        "ema_fast": ema_fast,
                        "ema_slow": ema_slow,
                        "atr": atr,
                        "adx": adx_value,
                        "candle_high": candle_high,
                        "dip_atr": round(dip_size, 3),
                    },
                }
                logger.info(
                    f"🎯 [TREND_DIP] {symbol}: LONG — дип {dip_size:.2f}×ATR "
                    f"({candle_high:.4f}→{current_price:.4f}), "
                    f"EMA↑, ADX={adx_value:.1f}, strength={strength:.2f}"
                )
                return [sig]

        # ---- SHORT: нисходящий тренд + резкий шип вверх ----
        elif is_trend_down:
            candle_low = current_candle.low
            if candle_low <= 0 or current_price <= 0:
                return []

            spike_size = (current_price - candle_low) / atr

            if dip_atr_min <= spike_size <= dip_atr_max and current_price > ema_fast:
                strength = min(1.0, spike_size / dip_atr_target) * confidence_base
                sig = {
                    "symbol": symbol,
                    "side": "sell",
                    "type": "trend_dip_short",
                    "price": current_price,
                    "strength": strength,
                    "confidence": confidence_base,
                    "reason": (
                        f"Тренд-дип SHORT: шип {spike_size:.2f}×ATR "
                        f"({candle_low:.4f}→{current_price:.4f}), "
                        f"EMA↓({ema_fast:.4f}<{ema_slow:.4f}), ADX={adx_value:.1f}"
                    ),
                    "timestamp": datetime.now().isoformat(),
                    "regime": regime_str,
                    "indicators": {
                        "ema_fast": ema_fast,
                        "ema_slow": ema_slow,
                        "atr": atr,
                        "adx": adx_value,
                        "candle_low": candle_low,
                        "spike_atr": round(spike_size, 3),
                    },
                }
                logger.info(
                    f"🎯 [TREND_DIP] {symbol}: SHORT — шип {spike_size:.2f}×ATR "
                    f"({candle_low:.4f}→{current_price:.4f}), "
                    f"EMA↓, ADX={adx_value:.1f}, strength={strength:.2f}"
                )
                return [sig]

        return []
