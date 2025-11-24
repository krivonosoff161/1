"""
SignalPipeline - Pipeline генерации и валидации сигналов.

Координирует:
- SignalGenerator (базовая генерация сигналов)
- FilterManager (применение всех фильтров)
- SignalValidator (финальная валидация)
"""

from typing import Any, Dict, List, Optional

from loguru import logger


class SignalPipeline:
    """
    Pipeline генерации и валидации сигналов.

    Поток:
    1. SignalGenerator генерирует базовые сигналы
    2. FilterManager применяет все фильтры
    3. SignalValidator финально валидирует
    """

    def __init__(
        self,
        signal_generator,
        filter_manager,
        signal_validator=None,
    ):
        """
        Инициализация SignalPipeline.

        Args:
            signal_generator: SignalGenerator для базовой генерации
            filter_manager: FilterManager для применения фильтров
            signal_validator: SignalValidator для финальной валидации (опционально)
        """
        self.signal_generator = signal_generator
        self.filter_manager = filter_manager
        self.signal_validator = signal_validator

        logger.info("✅ SignalPipeline инициализирован")

    async def generate_signal(
        self,
        symbol: str,
        market_data: Any,  # MarketData
        current_positions: Optional[Dict] = None,
        regime: Optional[str] = None,
        regime_params: Optional[Dict[str, Any]] = None,
        balance_profile: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Генерация и валидация сигнала для символа.

        Args:
            symbol: Торговый символ
            market_data: Рыночные данные
            current_positions: Текущие открытые позиции
            regime: Режим рынка (trending, ranging, choppy)
            regime_params: Параметры режима
            balance_profile: Профиль баланса (small, medium, large)

        Returns:
            Валидированный сигнал или None
        """
        try:
            # 1. Генерируем базовые сигналы через SignalGenerator
            base_signals = await self._generate_base_signals(
                symbol, market_data, regime, regime_params, balance_profile
            )

            if not base_signals:
                logger.debug(f"ℹ️ SignalPipeline: Нет базовых сигналов для {symbol}")
                return None

            # 2. Применяем фильтры через FilterManager
            filtered_signals = []
            for signal in base_signals:
                filtered_signal = await self.filter_manager.apply_all_filters(
                    symbol=symbol,
                    signal=signal,
                    market_data=market_data,
                    current_positions=current_positions,
                    regime=regime,
                    regime_params=regime_params,
                )

                if filtered_signal:
                    filtered_signals.append(filtered_signal)

            if not filtered_signals:
                logger.debug(
                    f"ℹ️ SignalPipeline: Все сигналы отфильтрованы для {symbol}"
                )
                return None

            # 3. Выбираем лучший сигнал (по силе)
            best_signal = max(filtered_signals, key=lambda s: s.get("strength", 0))

            # 4. Финальная валидация через SignalValidator
            if self.signal_validator:
                is_valid = await self.signal_validator.validate(
                    best_signal, market_data, regime, balance_profile
                )

                if not is_valid:
                    logger.debug(
                        f"ℹ️ SignalPipeline: Сигнал не прошел финальную валидацию для {symbol}"
                    )
                    return None

            logger.info(
                f"✅ SignalPipeline: Сгенерирован валидированный сигнал для {symbol} "
                f"(strength={best_signal.get('strength', 0):.2f}, side={best_signal.get('side', 'N/A')})"
            )

            return best_signal

        except Exception as e:
            logger.error(
                f"❌ SignalPipeline: Ошибка генерации сигнала для {symbol}: {e}",
                exc_info=True,
            )
            return None

    async def _generate_base_signals(
        self,
        symbol: str,
        market_data: Any,
        regime: Optional[str] = None,
        regime_params: Optional[Dict[str, Any]] = None,
        balance_profile: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Генерация базовых сигналов через SignalGenerator.

        Args:
            symbol: Торговый символ
            market_data: Рыночные данные
            regime: Режим рынка
            regime_params: Параметры режима
            balance_profile: Профиль баланса

        Returns:
            Список базовых сигналов
        """
        try:
            # Делегируем генерацию в SignalGenerator
            # Метод generate_signals или generate_signal должен быть в SignalGenerator
            if hasattr(self.signal_generator, "generate_signals"):
                signals = await self.signal_generator.generate_signals(
                    symbol, market_data, regime, regime_params
                )
            elif hasattr(self.signal_generator, "generate_signal"):
                signal = await self.signal_generator.generate_signal(
                    symbol, market_data, regime, regime_params
                )
                signals = [signal] if signal else []
            else:
                logger.warning(
                    f"⚠️ SignalPipeline: SignalGenerator не имеет метода generate_signals или generate_signal"
                )
                return []

            return signals

        except Exception as e:
            logger.error(
                f"❌ SignalPipeline: Ошибка генерации базовых сигналов для {symbol}: {e}",
                exc_info=True,
            )
            return []
