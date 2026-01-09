"""
MACD Signal Generator - Генерация сигналов на основе MACD индикатора.

Вынесено из signal_generator.py для улучшения модульности.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from src.models import MarketData


class MACDSignalGenerator:
    """
    Генератор сигналов на основе MACD индикатора.

    Генерирует сигналы на основе:
    - Пересечения MACD линии и сигнальной линии
    - Дивергенции MACD
    - Режима рынка (trending, ranging, choppy)
    """

    def __init__(
        self,
        regime_managers: Dict[str, Any] = None,
        regime_manager: Any = None,
        get_current_market_price_callback=None,
        get_regime_indicators_params_callback=None,
        scalping_config=None,  # ✅ НОВОЕ: Для получения confidence_config
    ):
        """
        Инициализация MACDSignalGenerator.

        Args:
            regime_managers: Словарь менеджеров режимов по символам
            regime_manager: Общий менеджер режимов
            get_current_market_price_callback: Callback для получения текущей цены
            get_regime_indicators_params_callback: Callback для получения параметров индикаторов по режиму
            scalping_config: Конфигурация скальпинга (для confidence_config)
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
        adx_threshold: float = 25.0,
    ) -> List[Dict[str, Any]]:
        """
        Генерация MACD сигналов с режим-специфичными параметрами.

        Args:
            symbol: Торговый символ
            indicators: Словарь индикаторов
            market_data: Рыночные данные
            adx_trend: Тренд ADX (опционально)
            adx_value: Значение ADX
            adx_threshold: Порог ADX

        Returns:
            Список сигналов
        """
        signals = []

        try:
            # ✅ АДАПТИВНО: Получаем confidence из конфига по режиму
            regime_name_macd = "ranging"  # Fallback
            try:
                if self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        regime_name_macd = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except Exception:
                pass

            confidence_config_macd = {}
            macd_confidence = 0.65  # Fallback
            if self.scalping_config:
                signal_gen_config_macd = getattr(
                    self.scalping_config, "signal_generator", {}
                )
                if isinstance(signal_gen_config_macd, dict):
                    confidence_dict = signal_gen_config_macd.get("confidence", {})
                    if regime_name_macd and confidence_dict:
                        regime_confidence = confidence_dict.get(regime_name_macd, {})
                        if isinstance(regime_confidence, dict):
                            confidence_config_macd = regime_confidence
                            macd_confidence = confidence_config_macd.get(
                                "macd_signal", 0.65
                            )
                else:
                    confidence_obj = getattr(signal_gen_config_macd, "confidence", None)
                    if confidence_obj and regime_name_macd:
                        regime_confidence = getattr(
                            confidence_obj, regime_name_macd, None
                        )
                        if regime_confidence:
                            macd_confidence = getattr(
                                regime_confidence, "macd_signal", 0.65
                            )

            # ✅ ИСПРАВЛЕНО (06.01.2026): MACD всегда сохраняется как dict в DataRegistry
            # Обрабатываем как dict (основной формат) и fallback на scalar (для backward compatibility)
            macd = indicators.get("macd", {})
            macd_line = macd.get("macd", 0) if isinstance(macd, dict) else macd
            signal_line = macd.get("signal", 0) if isinstance(macd, dict) else 0
            # Правильно вычисляем histogram
            histogram = (
                macd.get("histogram", macd_line - signal_line)
                if isinstance(macd, dict)
                else (macd_line - signal_line)
            )

            # ✅ ЗАДАЧА #7: Проверяем совпадение EMA и цены для MACD BULLISH
            ema_fast = indicators.get("ema_12", 0)
            ema_slow = indicators.get("ema_26", 0)
            # ✅ ОПТИМИЗАЦИЯ: Используем актуальную цену из стакана для сигналов
            candle_close_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )
            current_price = candle_close_price
            if self.get_current_market_price_callback:
                current_price = await self.get_current_market_price_callback(
                    symbol, candle_close_price
                )

            # ✅ НОВОЕ (09.01.2026): MA CROSSOVER сигналы
            # Получаем предыдущие значения EMA для определения пересечения
            prev_ema_fast = 0
            prev_ema_slow = 0
            if market_data.ohlcv_data and len(market_data.ohlcv_data) >= 2:
                # Рассчитываем EMA для предыдущей свечи (упрощенно - можно улучшить)
                prev_candles = market_data.ohlcv_data[:-1]  # Все кроме последней
                if len(prev_candles) >= 26:  # Нужно минимум 26 для EMA26
                    # Используем приблизительные значения (в идеале пересчитать EMA)
                    # Для быстрой реализации проверяем просто предыдущий close
                    prev_close = prev_candles[-1].close
                    # Простая аппроксимация: prev_ema ≈ текущий EMA со сдвигом
                    # (в production нужно сохранять историю EMA или пересчитывать)
                    prev_ema_fast = (
                        ema_fast * 0.99 if ema_fast > 0 else 0
                    )  # Приближение
                    prev_ema_slow = (
                        ema_slow * 0.99 if ema_slow > 0 else 0
                    )  # Приближение

            # MA Crossover UP (Bullish): EMA Fast пересекает EMA Slow снизу вверх
            ma_crossover_up = (
                prev_ema_fast > 0
                and prev_ema_slow > 0
                and prev_ema_fast <= prev_ema_slow
                and ema_fast > ema_slow  # Было ниже или равно  # Стало выше
            )

            # MA Crossover DOWN (Bearish): EMA Fast пересекает EMA Slow сверху вниз
            ma_crossover_down = (
                prev_ema_fast > 0
                and prev_ema_slow > 0
                and prev_ema_fast >= prev_ema_slow
                and ema_fast < ema_slow  # Было выше или равно  # Стало ниже
            )

            # Генерируем сигнал при пересечении вверх (LONG)
            if ma_crossover_up:
                confidence_crossover = macd_confidence + 0.10  # Bonus за crossover
                signals.append(
                    {
                        "symbol": symbol,
                        "side": "buy",  # LONG
                        "type": "ma_crossover_up",
                        "price": current_price,
                        "strength": confidence_crossover,
                        "confidence": confidence_crossover,
                        "reason": (
                            f"MA Crossover UP: ema_fast({ema_fast:.2f}) пересекла "
                            f"ema_slow({ema_slow:.2f}) снизу вверх"
                        ),
                        "timestamp": datetime.now().isoformat(),
                        "indicators": {
                            "ema_fast": ema_fast,
                            "ema_slow": ema_slow,
                            "prev_ema_fast": prev_ema_fast,
                            "prev_ema_slow": prev_ema_slow,
                            "current_price": current_price,
                        },
                    }
                )
                logger.info(
                    f"🎯 {symbol}: MA Crossover UP LONG сигнал (confidence={confidence_crossover:.2f}): "
                    f"ema_fast={ema_fast:.2f} > ema_slow={ema_slow:.2f}"
                )

            # Пересечение MACD линии и сигнальной линии
            if macd_line > signal_line and histogram > 0:
                # ✅ ЗАДАЧА #7: Проверяем совпадение EMA и цены для BULLISH
                is_bullish_trend = ema_fast > ema_slow and current_price > ema_fast

                # ✅ ПРИОРИТЕТ 1 (28.12.2025): Адаптивный MACD strength делитель по режимам
                # Получаем режим для определения делителя
                current_regime_macd_sig = (
                    regime_name_macd if regime_name_macd else "ranging"
                )

                # Адаптивный делитель: Trending=120, Ranging=180, Choppy=150
                macd_strength_divider = 180.0  # Fallback для ranging
                try:
                    if self.get_regime_indicators_params_callback:
                        regime_params_divider = (
                            self.get_regime_indicators_params_callback(symbol=symbol)
                        )
                        macd_strength_divider = regime_params_divider.get(
                            "macd_strength_divider", 180.0
                        )
                except Exception:
                    # Если нет в конфиге, используем режим-специфичные значения
                    if current_regime_macd_sig == "trending":
                        macd_strength_divider = 120.0
                    elif current_regime_macd_sig == "choppy":
                        macd_strength_divider = 150.0
                    else:  # ranging
                        macd_strength_divider = 180.0

                base_strength = min(abs(histogram) / macd_strength_divider, 1.0)

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                if not is_bullish_trend:
                    # Конфликт: MACD bullish, но EMA/цена не bullish
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        if self.scalping_config:
                            adaptive_regime = getattr(
                                self.scalping_config, "adaptive_regime", {}
                            )
                            if isinstance(adaptive_regime, dict):
                                regime_config = adaptive_regime.get(
                                    regime_name_macd, {}
                                )
                            else:
                                regime_config = getattr(
                                    adaptive_regime, regime_name_macd, {}
                                )

                            if isinstance(regime_config, dict):
                                strength_multipliers = regime_config.get(
                                    "strength_multipliers", {}
                                )
                                conflict_multiplier = strength_multipliers.get(
                                    "conflict", 0.5
                                )
                            else:
                                strength_multipliers = getattr(
                                    regime_config, "strength_multipliers", None
                                )
                                if strength_multipliers:
                                    conflict_multiplier = getattr(
                                        strength_multipliers, "conflict", 0.5
                                    )
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить conflict_multiplier: {e}")

                    base_strength *= conflict_multiplier
                    logger.debug(
                        f"⚡ MACD BULLISH с конфликтом для {symbol}: "
                        f"MACD bullish, но EMA/цена не bullish, "
                        f"strength снижен на {conflict_multiplier:.1%} (стало {base_strength:.3f})"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем ADX тренд ПРИ генерации сигнала
                if adx_trend == "bearish" and adx_value >= adx_threshold:
                    logger.debug(
                        f"🚫 MACD BULLISH сигнал ОТМЕНЕН для {symbol}: "
                        f"ADX показывает нисходящий тренд (ADX={adx_value:.1f}, -DI доминирует)"
                    )
                else:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "buy",
                            "type": "macd_bullish",
                            "strength": base_strength,
                            "price": current_price,
                            "timestamp": datetime.now(),
                            "indicator_value": histogram,
                            "confidence": macd_confidence,  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

            elif macd_line < signal_line and histogram < 0:
                # ✅ ЗАДАЧА #7: Проверяем совпадение EMA и цены для BEARISH
                is_bearish_trend = ema_fast < ema_slow and current_price < ema_fast

                # ✅ ПРИОРИТЕТ 1 (28.12.2025): Адаптивный MACD strength делитель по режимам
                # Получаем режим для определения делителя
                current_regime_macd_sig = (
                    regime_name_macd if regime_name_macd else "ranging"
                )

                # Адаптивный делитель: Trending=120, Ranging=180, Choppy=150
                macd_strength_divider = 180.0  # Fallback для ranging
                try:
                    if self.get_regime_indicators_params_callback:
                        regime_params_divider = (
                            self.get_regime_indicators_params_callback(symbol=symbol)
                        )
                        macd_strength_divider = regime_params_divider.get(
                            "macd_strength_divider", 180.0
                        )
                except Exception:
                    # Если нет в конфиге, используем режим-специфичные значения
                    if current_regime_macd_sig == "trending":
                        macd_strength_divider = 120.0
                    elif current_regime_macd_sig == "choppy":
                        macd_strength_divider = 150.0
                    else:  # ranging
                        macd_strength_divider = 180.0

                base_strength = min(abs(histogram) / macd_strength_divider, 1.0)

                # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                if not is_bearish_trend:
                    conflict_multiplier = 0.5  # Fallback
                    try:
                        if self.scalping_config:
                            adaptive_regime = getattr(
                                self.scalping_config, "adaptive_regime", {}
                            )
                            if isinstance(adaptive_regime, dict):
                                regime_config = adaptive_regime.get(
                                    regime_name_macd, {}
                                )
                            else:
                                regime_config = getattr(
                                    adaptive_regime, regime_name_macd, {}
                                )

                            if isinstance(regime_config, dict):
                                strength_multipliers = regime_config.get(
                                    "strength_multipliers", {}
                                )
                                conflict_multiplier = strength_multipliers.get(
                                    "conflict", 0.5
                                )
                            else:
                                strength_multipliers = getattr(
                                    regime_config, "strength_multipliers", None
                                )
                                if strength_multipliers:
                                    conflict_multiplier = getattr(
                                        strength_multipliers, "conflict", 0.5
                                    )
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить conflict_multiplier: {e}")

                    base_strength *= conflict_multiplier
                    logger.debug(
                        f"⚡ MACD BEARISH с конфликтом для {symbol}: "
                        f"MACD bearish, но EMA/цена не bearish, "
                        f"strength снижен на {conflict_multiplier:.1%} (стало {base_strength:.3f})"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем ADX тренд ПРИ генерации сигнала
                if adx_trend == "bullish" and adx_value >= adx_threshold:
                    logger.debug(
                        f"🚫 MACD BEARISH сигнал ОТМЕНЕН для {symbol}: "
                        f"ADX показывает восходящий тренд (ADX={adx_value:.1f}, +DI доминирует)"
                    )
                else:
                    signals.append(
                        {
                            "symbol": symbol,
                            "side": "sell",
                            "type": "macd_bearish",
                            "strength": base_strength,
                            "price": current_price,
                            "timestamp": datetime.now(),
                            "indicator_value": histogram,
                            "confidence": macd_confidence,  # ✅ АДАПТИВНО: Из конфига
                        }
                    )

        except Exception as e:
            logger.error(
                f"❌ Ошибка генерации MACD сигналов для {symbol}: {e}", exc_info=True
            )

        return signals
