"""
RSI Signal Generator - Генерация сигналов на основе RSI индикатора.

Вынесено из signal_generator.py для улучшения модульности.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from src.models import MarketData


class RSISignalGenerator:
    """
    Генератор сигналов на основе RSI индикатора.

    Генерирует сигналы на основе:
    - RSI перекупленности/перепроданности
    - Тренда EMA
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
        Инициализация RSISignalGenerator.

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
        Генерация RSI сигналов с режим-специфичными порогами.

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
            rsi = indicators.get("rsi", 50)

            # ✅ Получаем режим-специфичные параметры для текущего символа
            if self.get_regime_indicators_params_callback:
                regime_params = self.get_regime_indicators_params_callback(
                    symbol=symbol
                )
            else:
                regime_params = {}

            rsi_oversold = regime_params.get("rsi_oversold", 30)
            rsi_overbought = regime_params.get("rsi_overbought", 70)

            # ✅ НОВОЕ (09.01.2026): Адаптивные RSI пороги по направлению тренда
            # В uptrend: LONG при RSI < 50 (не ждать глубокой перепроданности 30)
            # В downtrend: SHORT при RSI > 50 (не ждать сильной перекупленности 70)
            ema_fast = indicators.get("ema_12", 0)
            ema_slow = indicators.get("ema_26", 0)

            # Определяем направление тренда по EMA
            is_uptrend = ema_fast > ema_slow
            is_downtrend = ema_fast < ema_slow

            # Адаптируем пороги
            if is_uptrend:
                rsi_oversold_adaptive = 50  # В uptrend ловим LONG раньше
                rsi_overbought_adaptive = rsi_overbought  # Стандартный порог для SHORT
            elif is_downtrend:
                rsi_oversold_adaptive = rsi_oversold  # Стандартный порог для LONG
                rsi_overbought_adaptive = 50  # В downtrend ловим SHORT раньше
            else:
                # Нейтральный тренд - стандартные пороги
                rsi_oversold_adaptive = rsi_oversold
                rsi_overbought_adaptive = rsi_overbought

            # Получаем текущий режим для логирования
            regime_manager = self.regime_managers.get(symbol) or self.regime_manager
            current_regime = (
                regime_manager.get_current_regime() if regime_manager else "N/A"
            )

            # ✅ Получаем EMA для проверки тренда
            ema_fast = indicators.get("ema_12", 0)
            ema_slow = indicators.get("ema_26", 0)

            # ✅ Получаем актуальную цену из стакана для сигналов
            candle_close_price = (
                market_data.ohlcv_data[-1].close if market_data.ohlcv_data else 0.0
            )

            current_price = candle_close_price
            if self.get_current_market_price_callback:
                current_price = await self.get_current_market_price_callback(
                    symbol, candle_close_price
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем confidence_config_rsi ДО всех условий
            regime_name_for_conf = "ranging"  # Fallback
            try:
                if self.regime_manager:
                    regime_obj = self.regime_manager.get_current_regime()
                    if regime_obj:
                        regime_name_for_conf = (
                            regime_obj.lower()
                            if isinstance(regime_obj, str)
                            else str(regime_obj).lower()
                        )
            except Exception:
                pass

            # Получаем confidence значения из конфига
            confidence_config_rsi = {}
            if self.scalping_config:
                signal_gen_config_conf = getattr(
                    self.scalping_config, "signal_generator", {}
                )
                if isinstance(signal_gen_config_conf, dict):
                    confidence_dict = signal_gen_config_conf.get("confidence", {})
                    if regime_name_for_conf and confidence_dict:
                        regime_confidence = confidence_dict.get(
                            regime_name_for_conf, {}
                        )
                        if isinstance(regime_confidence, dict):
                            confidence_config_rsi = regime_confidence
                else:
                    confidence_obj = getattr(signal_gen_config_conf, "confidence", None)
                    if confidence_obj and regime_name_for_conf:
                        regime_confidence = getattr(
                            confidence_obj, regime_name_for_conf, None
                        )
                        if regime_confidence:
                            confidence_config_rsi = {
                                "bullish_strong": getattr(
                                    regime_confidence, "bullish_strong", 0.7
                                ),
                                "bullish_normal": getattr(
                                    regime_confidence, "bullish_normal", 0.6
                                ),
                                "rsi_signal": getattr(
                                    regime_confidence, "rsi_signal", 0.6
                                ),
                            }

            # Перепроданность (покупка) - используем адаптивный порог
            if rsi < rsi_oversold_adaptive:
                # Проверяем тренд через EMA - если конфликт, снижаем confidence
                is_downtrend_check = ema_fast < ema_slow and current_price < ema_fast

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем текущий режим для проверки блокировки
                current_regime_check = "ranging"  # Fallback
                try:
                    if self.regime_manager:
                        regime_obj = self.regime_manager.get_current_regime()
                        if regime_obj:
                            current_regime_check = (
                                regime_obj.lower()
                                if isinstance(regime_obj, str)
                                else str(regime_obj).lower()
                            )
                except Exception as e:
                    logger.debug(f"⚠️ Не удалось получить режим для блокировки: {e}")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: В trending режиме - полная блокировка противотрендовых сигналов
                should_block = current_regime_check == "trending" and is_downtrend_check
                if should_block:
                    logger.debug(
                        f"🚫 RSI OVERSOLD сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: "
                        f"trending режим + EMA bearish (конфликт с трендом)"
                    )
                else:
                    # Нормализованная сила: от 0 до 1
                    strength = min(
                        1.0, (rsi_oversold_adaptive - rsi) / rsi_oversold_adaptive
                    )

                    # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                    has_conflict = False
                    if is_downtrend_check:
                        # Конфликт: RSI oversold (LONG) vs EMA bearish (DOWN)
                        # Получаем strength_multiplier для конфликта из конфига
                        conflict_multiplier = 0.5  # Fallback
                        try:
                            if self.scalping_config:
                                adaptive_regime = getattr(
                                    self.scalping_config, "adaptive_regime", {}
                                )
                                if isinstance(adaptive_regime, dict):
                                    regime_config = adaptive_regime.get(
                                        current_regime_check, {}
                                    )
                                else:
                                    regime_config = getattr(
                                        adaptive_regime, current_regime_check, {}
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
                            logger.debug(
                                f"⚠️ Не удалось получить conflict_multiplier: {e}"
                            )

                        # ✅ ЗАДАЧА #7: Снижаем strength при конфликте
                        strength *= conflict_multiplier

                        # ✅ АДАПТИВНО: Сниженная уверенность из конфига (50% от нормальной)
                        normal_conf = confidence_config_rsi.get("rsi_signal", 0.6)
                        confidence = (
                            normal_conf * 0.5
                        )  # Конфликт = 50% от нормальной уверенности
                        has_conflict = True
                        logger.debug(
                            f"⚡ RSI OVERSOLD с конфликтом для {symbol}: "
                            f"RSI oversold, но EMA/цена не bullish, "
                            f"strength снижен на {conflict_multiplier:.1%} (стало {strength:.3f})"
                        )
                    else:
                        confidence = confidence_config_rsi.get(
                            "rsi_signal", 0.6
                        )  # ✅ АДАПТИВНО: Из конфига
                        has_conflict = False

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем ADX тренд ПРИ генерации сигнала
                    if adx_trend == "bearish" and adx_value >= adx_threshold:
                        # Сильный нисходящий тренд - не генерируем BUY сигнал
                        logger.debug(
                            f"🚫 RSI OVERSOLD сигнал ОТМЕНЕН для {symbol}: "
                            f"ADX показывает нисходящий тренд (ADX={adx_value:.1f}, -DI доминирует)"
                        )
                    else:
                        signals.append(
                            {
                                "symbol": symbol,
                                "side": "buy",
                                "type": "rsi_oversold",
                                "strength": strength,
                                "price": current_price,
                                "timestamp": datetime.now(),
                                "indicator_value": rsi,
                                "confidence": confidence,
                                "has_conflict": has_conflict,  # ✅ Флаг конфликта для order_executor
                            }
                        )

            # Перекупленность (продажа) - используем адаптивный порог
            elif rsi > rsi_overbought:
                # Проверяем тренд через EMA - если конфликт, снижаем confidence
                is_uptrend = ema_fast > ema_slow and current_price > ema_fast

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем текущий режим для проверки блокировки
                current_regime_check = "ranging"  # Fallback
                try:
                    if self.regime_manager:
                        regime_obj = self.regime_manager.get_current_regime()
                        if regime_obj:
                            current_regime_check = (
                                regime_obj.lower()
                                if isinstance(regime_obj, str)
                                else str(regime_obj).lower()
                            )
                except Exception as e:
                    logger.debug(f"⚠️ Не удалось получить режим для блокировки: {e}")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: В trending режиме - полная блокировка противотрендовых сигналов
                should_block = current_regime_check == "trending" and is_uptrend
                if should_block:
                    logger.debug(
                        f"🚫 RSI OVERBOUGHT сигнал ПОЛНОСТЬЮ ЗАБЛОКИРОВАН для {symbol}: "
                        f"trending режим + EMA bullish (конфликт с трендом)"
                    )
                else:
                    # Нормализованная сила: от 0 до 1
                    strength = min(1.0, (rsi - rsi_overbought) / (100 - rsi_overbought))

                    # ✅ ЗАДАЧА #7: При конфликте снижаем strength адаптивно под режим
                    has_conflict = False
                    if is_uptrend:
                        # Конфликт: RSI overbought (SHORT) vs EMA bullish (UP)
                        conflict_multiplier = 0.5  # Fallback
                        try:
                            if self.scalping_config:
                                adaptive_regime = getattr(
                                    self.scalping_config, "adaptive_regime", {}
                                )
                                if isinstance(adaptive_regime, dict):
                                    regime_config = adaptive_regime.get(
                                        current_regime_check, {}
                                    )
                                else:
                                    regime_config = getattr(
                                        adaptive_regime, current_regime_check, {}
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
                            logger.debug(
                                f"⚠️ Не удалось получить conflict_multiplier: {e}"
                            )

                        # ✅ ЗАДАЧА #7: Снижаем strength при конфликте
                        strength *= conflict_multiplier

                        # ✅ АДАПТИВНО: Сниженная уверенность из конфига (50% от нормальной)
                        normal_conf = confidence_config_rsi.get("rsi_signal", 0.6)
                        confidence = (
                            normal_conf * 0.5
                        )  # Конфликт = 50% от нормальной уверенности
                        has_conflict = True
                        logger.debug(
                            f"⚡ RSI OVERBOUGHT с конфликтом для {symbol}: "
                            f"RSI({rsi:.2f}) > overbought({rsi_overbought}), "
                            f"но EMA показывает восходящий тренд → быстрый скальп на коррекции, "
                            f"strength снижен на {conflict_multiplier:.1%} (стало {strength:.3f}), "
                            f"confidence={confidence:.1f}"
                        )
                    else:
                        confidence = confidence_config_rsi.get(
                            "rsi_signal", 0.6
                        )  # ✅ АДАПТИВНО: Из конфига
                        has_conflict = False

                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем ADX тренд ПРИ генерации сигнала
                    if adx_trend == "bullish" and adx_value >= adx_threshold:
                        # Сильный восходящий тренд - не генерируем SELL сигнал
                        logger.debug(
                            f"🚫 RSI OVERBOUGHT сигнал ОТМЕНЕН для {symbol}: "
                            f"ADX показывает восходящий тренд (ADX={adx_value:.1f}, +DI доминирует)"
                        )
                    else:
                        signals.append(
                            {
                                "symbol": symbol,
                                "side": "sell",
                                "type": "rsi_overbought",
                                "strength": strength,
                                "price": current_price,
                                "timestamp": datetime.now(),
                                "indicator_value": rsi,
                                "confidence": confidence,
                                "has_conflict": has_conflict,  # ✅ Флаг конфликта для order_executor
                            }
                        )

        except Exception as e:
            logger.error(
                f"❌ Ошибка генерации RSI сигналов для {symbol}: {e}", exc_info=True
            )

        return signals
