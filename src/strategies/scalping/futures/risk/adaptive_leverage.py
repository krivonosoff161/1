"""
Adaptive Leverage - Адаптивный леверидж на основе качества сигнала.

Определяет оптимальный леверидж (3, 5, 10, 20, 30) в зависимости от силы сигнала.
"""

from typing import Any, Dict, Optional

from loguru import logger


class AdaptiveLeverage:
    """
    Адаптивный леверидж на основе качества сигнала.

    Определяет оптимальный леверидж в зависимости от:
    - Силы сигнала (signal_strength)
    - Режима рынка (trending, ranging, choppy)
    - Волатильности (ATR)
    - Качества индикаторов (RSI, MACD, ADX)
    """

    def __init__(self, config=None):
        """
        Инициализация AdaptiveLeverage.

        Args:
            config: Конфигурация бота
        """
        self.config = config

        # ✅ P0-2 FIX: Leverage map из конфига с безопасными дефолтами
        cfg = config if isinstance(config, dict) else {}
        # Навигация: config → scalping → adaptive_leverage → leverage_map
        al_cfg = cfg.get("scalping", {}).get("adaptive_leverage", {})
        lev_map_cfg = al_cfg.get("leverage_map", {})
        if lev_map_cfg:
            self.leverage_map = {k: int(v) for k, v in lev_map_cfg.items()}
        else:
            # Безопасные дефолты (снижены с 20/30 до 15/20)
            self.leverage_map = {
                "very_weak": 3,  # 0.0-0.3
                "weak": 5,  # 0.3-0.5
                "medium": 10,  # 0.5-0.7
                "strong": 15,  # 0.7-0.9 (было 20)
                "very_strong": 20,  # 0.9-1.0 (было 30)
            }

        # Минимальный и максимальный леверидж из конфига
        self.min_leverage = int(al_cfg.get("min_leverage", 3))
        self.max_leverage = int(al_cfg.get("max_leverage", 20))  # был 30

        # 🔴 BUG #24 FIX: Leverage limits as % of equity, not hardcoded $
        # These will be used to calculate margin thresholds dynamically
        self.position_size_limit_1_percent = (
            0.20  # 20% of equity (SCALPING: повышен с 10%)
        )
        self.position_size_limit_2_percent = (
            0.20  # 20% of equity (SCALPING: повышен с 10%)
        )

    async def calculate_leverage(
        self,
        signal: Dict[str, Any],
        regime: Optional[str] = None,
        volatility: Optional[float] = None,
        client: Optional[Any] = None,
        position_size_usd: Optional[float] = None,
    ) -> int:
        """
        Расчет адаптивного левериджа на основе качества сигнала.

        Args:
            signal: Торговый сигнал
            regime: Режим рынка (trending, ranging, choppy)
            volatility: Волатильность (ATR в процентах)
            client: OKXFuturesClient (опционально, для округления leverage до доступного)

        Returns:
            Оптимальный леверидж (3, 5, 10, 20, 30), округленный до доступного на бирже
        """
        try:
            # ✅ ИСПРАВЛЕНО: Инициализируем leverage дефолтным значением в начале
            # Используем средний леверидж по умолчанию (из профиля символа или 5)
            leverage = 5  # Дефолтное значение

            # Получаем силу сигнала
            signal_strength = signal.get("strength", 0.5)
            if signal_strength < 0:
                signal_strength = 0.0
            elif signal_strength > 1.0:
                signal_strength = 1.0

            # Корректируем на основе режима рынка
            regime_multiplier = 1.0
            if regime == "trending":
                regime_multiplier = 1.2  # В тренде можно больше левериджа
            elif regime == "ranging":
                regime_multiplier = 0.8  # В боковике меньше левериджа
            elif regime == "choppy":
                regime_multiplier = 0.8  # В хаосе меньше левериджа

            # Корректируем на основе волатильности
            volatility_multiplier = 1.0
            if volatility is not None:
                if volatility > 0.05:  # Высокая волатильность (>5%)
                    volatility_multiplier = 0.7  # Уменьшаем леверидж
                elif volatility < 0.01:  # Низкая волатильность (<1%)
                    volatility_multiplier = 1.3  # Увеличиваем леверидж

            # Применяем корректировки
            adjusted_strength = (
                signal_strength * regime_multiplier * volatility_multiplier
            )
            adjusted_strength = max(
                0.0, min(1.0, adjusted_strength)
            )  # Ограничиваем 0-1

            # Определяем категорию качества сигнала
            if adjusted_strength < 0.3:
                category = "very_weak"
            elif adjusted_strength < 0.5:
                category = "weak"
            elif adjusted_strength < 0.7:
                category = "medium"
            elif adjusted_strength < 0.9:
                category = "strong"
            else:
                category = "very_strong"

            leverage = self.leverage_map.get(category, 5)

            # ✅ ПРАВКА #12: Снижаем леверидж для ranging (максимум 15x) - УВЕЛИЧЕНО ДЛЯ ЛУЧШЕЙ ЭФФЕКТИВНОСТИ
            # 🔥 ИЗМЕНЕНО: Лимит увеличен с 10x до 15x для ranging (2026-02-08)
            if regime == "ranging":
                leverage = min(leverage, 15)  # Максимум 15x для ranging (было 10x)

            # ✅ КРИТИЧНОЕ ИСПРАВЛЕНИЕ (25.12.2025): Ограничение плеча по размеру позиции
            # 🔴 BUG #24 FIX: Use % of equity instead of hardcoded $ values
            # ВАЖНО: position_size_usd может быть как margin, так и notional
            # Если это margin, то notional = margin * leverage (будет пересчитано в signal_coordinator)
            # Если это notional, то используем напрямую
            # Для безопасности считаем, что это margin, и применяем более строгие ограничения
            if position_size_usd is not None and position_size_usd > 0 and client:
                try:
                    # Get current balance to calculate thresholds as % of equity
                    current_balance = (
                        await client.get_balance()
                        if hasattr(client, "get_balance")
                        else None
                    )
                    if current_balance and current_balance > 0:
                        # Calculate margin limits as % of equity
                        limit_high = (
                            current_balance * self.position_size_limit_1_percent
                        )  # 10%
                        limit_medium = (
                            current_balance * self.position_size_limit_2_percent
                        )  # 5%

                        if position_size_usd > limit_high:
                            leverage = min(leverage, 10)
                            logger.info(
                                f"🔒 [LEVERAGE_LIMIT] {signal.get('symbol', 'N/A')}: Margin ${position_size_usd:.2f} > ${limit_high:.2f} (10% of equity), "
                                f"ограничение плеча до 10x для защиты от ADL"
                            )
                        elif position_size_usd > limit_medium:
                            leverage = min(leverage, 15)
                            logger.info(
                                f"🔒 [LEVERAGE_LIMIT] {signal.get('symbol', 'N/A')}: Margin ${position_size_usd:.2f} > ${limit_medium:.2f} (5% of equity), "
                                f"ограничение плеча до 15x"
                            )
                except Exception as e:
                    logger.debug(
                        f"⚠️ [LEVERAGE_LIMIT] Error calculating equity-based limits: {e}"
                    )
                    # Fallback to old hardcoded values for backward compatibility
                    if position_size_usd > 100:
                        leverage = min(leverage, 10)
                    elif position_size_usd > 50:
                        leverage = min(leverage, 15)

            # Ограничиваем минимальным и максимальным значением
            leverage = max(self.min_leverage, min(self.max_leverage, leverage))

            # ✅ ИСПРАВЛЕНИЕ: Форматируем volatility отдельно для правильной работы f-string
            volatility_str = f"{volatility:.4f}" if volatility is not None else "N/A"

            symbol = signal.get("symbol", "N/A")

            # 🔇 ИЗМЕНЕНО (2026-02-08): INFO → DEBUG для снижения объема логов
            # Раскомментировать для детальной диагностики leverage расчетов
            # logger.info(
            #     f"📊 [ADAPTIVE_LEVERAGE] {symbol}: Расчет leverage | "
            #     f"strength={signal_strength:.2f}, regime={regime}, "
            #     f"volatility={volatility_str}, "
            #     f"regime_multiplier={regime_multiplier:.2f}, "
            #     f"volatility_multiplier={volatility_multiplier:.2f}, "
            #     f"adjusted_strength={adjusted_strength:.2f}, category={category}, "
            #     f"requested_leverage={leverage}x (до округления)"
            # )

            # ✅ ИСПРАВЛЕНИЕ #4: Округляем leverage до доступного на бирже
            if client and symbol != "N/A":
                try:
                    original_leverage = leverage

                    # ✅ ПРАВКА #8: Получить доступные левериджи и не превышать максимальный
                    leverage_info = await client.get_instrument_leverage_info(symbol)
                    available_leverages = leverage_info.get("available_leverages", [])
                    max_available = leverage_info.get("max_leverage", 20)

                    if available_leverages:
                        # 🔇 ИЗМЕНЕНО (2026-02-08): INFO → DEBUG
                        # logger.info(
                        #     f"📊 [ADAPTIVE_LEVERAGE] {symbol}: Available leverages: {available_leverages}, max={max_available}x"
                        # )
                        # Не превышать доступный максимум
                        leverage = min(leverage, max_available)

                    leverage = await client.round_leverage_to_available(
                        symbol, leverage
                    )

                    if leverage != original_leverage:
                        # 🔇 ИЗМЕНЕНО (2026-02-08): Сократили избыточное логирование
                        # Логируем только значимые изменения
                        logger.info(
                            f"⚠️ [ADAPTIVE_LEVERAGE] {symbol}: Леверидж изменен {original_leverage}x → {leverage}x (округление до доступного)"
                        )
                    # else:
                    #     logger.info(
                    #         f"✅ [ADAPTIVE_LEVERAGE] {symbol}: Округление не требуется | "
                    #         f"{leverage}x уже доступен на бирже"
                    #     )
                except Exception as e:
                    logger.warning(
                        f"⚠️ [ADAPTIVE_LEVERAGE] {symbol}: Ошибка округления leverage: {e}, "
                        f"используем рассчитанный leverage={leverage}x"
                    )

            # 🔇 ИЗМЕНЕНО (2026-02-08): Логируем только финальный результат, без деталей
            logger.info(
                f"✅ [ADAPTIVE_LEVERAGE] {symbol}: leverage={leverage}x (category={category})"
            )

            return leverage

        except Exception as e:
            logger.error(f"❌ Ошибка расчета адаптивного левериджа: {e}", exc_info=True)
            return 5  # Fallback: стандартный леверидж

    async def get_leverage_for_signal(
        self,
        signal: Dict[str, Any],
        indicators: Optional[Dict[str, Any]] = None,
        client: Optional[Any] = None,
        position_size_usd: Optional[float] = None,
    ) -> int:
        """
        Получение левериджа для сигнала с учетом индикаторов.

        Args:
            signal: Торговый сигнал
            indicators: Словарь индикаторов (RSI, MACD, ADX и т.д.)
            client: OKXFuturesClient (опционально, для округления leverage)
            position_size_usd: Размер позиции в USD (опционально, для ограничения плеча)

        Returns:
            Оптимальный леверидж
        """
        try:
            regime = signal.get("regime")
            volatility = None

            # Получаем волатильность из индикаторов если доступна
            if indicators:
                atr = indicators.get("atr")
                current_price = signal.get("price", 0)
                if atr and current_price > 0:
                    volatility = (atr / current_price) if current_price > 0 else None

            return await self.calculate_leverage(
                signal, regime, volatility, client, position_size_usd
            )

        except Exception as e:
            logger.error(f"❌ Ошибка получения левериджа для сигнала: {e}")
            return 5  # Fallback
