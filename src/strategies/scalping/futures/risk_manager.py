"""
Risk Manager для Futures торговли.

Ответственность:
- Расчет размера позиции с учетом баланса и режима
- Проверка безопасности маржи
- Интеграция с ConfigManager
- Интеграция с существующими risk модулями
"""

from typing import Any, Dict, Optional

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig

from .config.config_manager import ConfigManager
from .risk.liquidation_protector import LiquidationProtector
from .risk.margin_monitor import MarginMonitor
from .risk.max_size_limiter import MaxSizeLimiter


class FuturesRiskManager:
    """
    Менеджер рисков для Futures торговли.

    Централизует всю логику управления рисками.
    """

    def __init__(
        self,
        config: BotConfig,
        client: OKXFuturesClient,
        config_manager: ConfigManager,
        liquidation_protector: Optional[LiquidationProtector] = None,
        margin_monitor: Optional[MarginMonitor] = None,
        max_size_limiter: Optional[MaxSizeLimiter] = None,
    ):
        """
        Args:
            config: Конфигурация бота
            client: Futures клиент
            config_manager: Config Manager
            liquidation_protector: Защита от ликвидации (опционально)
            margin_monitor: Мониторинг маржи (опционально)
            max_size_limiter: Ограничитель размера (опционально)
        """
        self.config = config
        self.scalping_config = config.scalping
        self.client = client
        self.config_manager = config_manager
        self.liquidation_protector = liquidation_protector
        self.margin_monitor = margin_monitor
        self.max_size_limiter = max_size_limiter

        # Получаем symbol_profiles из config_manager
        self.symbol_profiles = config_manager.get_symbol_profiles()

        logger.info("✅ FuturesRiskManager initialized")

    async def calculate_position_size(
        self,
        balance: float,
        price: float,
        signal: Dict[str, Any],
        signal_generator=None,
    ) -> float:
        """
        Рассчитывает размер позиции с учетом Balance Profiles и режима рынка.

        Args:
            balance: Текущий баланс
            price: Текущая цена
            signal: Торговый сигнал
            signal_generator: Signal generator для определения режима

        Returns:
            float: Размер позиции в USD
        """
        try:
            symbol = signal.get("symbol")
            symbol_regime = signal.get("regime")

            # Определяем режим если не указан
            if symbol and not symbol_regime and signal_generator:
                if hasattr(signal_generator, "regime_managers"):
                    manager = signal_generator.regime_managers.get(symbol)
                    if manager:
                        symbol_regime = manager.get_current_regime()
                elif (
                    hasattr(signal_generator, "regime_manager")
                    and signal_generator.regime_manager
                ):
                    symbol_regime = signal_generator.regime_manager.get_current_regime()

            # Получаем balance profile
            balance_profile = self.config_manager.get_balance_profile(balance)

            base_usd_size = balance_profile["base_position_usd"]
            min_usd_size = balance_profile["min_position_usd"]
            max_usd_size = balance_profile["max_position_usd"]

            # ✅ Применяем per-symbol множитель
            if symbol:
                symbol_profile = self.symbol_profiles.get(symbol, {})
                if symbol_profile:
                    symbol_dict = (
                        self.config_manager.to_dict(symbol_profile)
                        if not isinstance(symbol_profile, dict)
                        else symbol_profile
                    )
                    position_multiplier = symbol_dict.get("position_multiplier")

                    if position_multiplier is not None:
                        original_size = base_usd_size
                        if position_multiplier != 1.0:
                            base_usd_size = base_usd_size * float(position_multiplier)
                            logger.info(
                                f"📊 Per-symbol multiplier для {symbol}: {position_multiplier}x "
                                f"→ размер ${original_size:.2f} → ${base_usd_size:.2f}"
                            )

                # Проверяем position overrides в symbol_profiles
                if symbol_regime and symbol_profile:
                    regime_profile = symbol_profile.get(symbol_regime.lower(), {})
                    if regime_profile:
                        regime_dict = (
                            self.config_manager.to_dict(regime_profile)
                            if not isinstance(regime_profile, dict)
                            else regime_profile
                        )
                        position_overrides = regime_dict.get("position", {})

                        if position_overrides:
                            # Проверяем max_position_usd override
                            if position_overrides.get("max_position_usd") is not None:
                                symbol_max = float(
                                    position_overrides["max_position_usd"]
                                )

                                # Если symbol_max БОЛЬШЕ balance_max - используем symbol_max
                                if symbol_max > max_usd_size:
                                    logger.debug(
                                        f"📊 Max position size из symbol_profiles (${symbol_max:.2f}) больше "
                                        f"balance_profile (${max_usd_size:.2f}), используем ${symbol_max:.2f}"
                                    )
                                    max_usd_size = symbol_max
                                else:
                                    logger.debug(
                                        f"📊 Max position size из symbol_profiles (${symbol_max:.2f}) меньше или равно "
                                        f"balance_profile (${max_usd_size:.2f}), игнорируем (используем ${max_usd_size:.2f})"
                                    )

                                # Проверка конфигурации
                                if symbol_max < min_usd_size:
                                    logger.error(
                                        f"❌ ОШИБКА КОНФИГУРАЦИИ: max_position_usd из symbol_profiles (${symbol_max:.2f}) меньше "
                                        f"min_position_usd (${min_usd_size:.2f})! Невозможно открыть позицию. "
                                        f"Исправьте конфиг: увеличьте max_position_usd или уменьшите min_position_usd для {symbol}."
                                    )
                                    return 0.0

                            if (
                                position_overrides.get("max_position_percent")
                                is not None
                            ):
                                balance_profile["max_position_percent"] = float(
                                    position_overrides["max_position_percent"]
                                )

            # Применяем лимиты
            position_usd = max(min_usd_size, min(base_usd_size, max_usd_size))

            # Проверяем max_size_limiter
            if self.max_size_limiter:
                position_usd = await self.max_size_limiter.check_and_limit(
                    position_usd, balance_profile
                )

            logger.info(
                f"📊 Position size calculated: ${position_usd:.2f} "
                f"(base: ${base_usd_size:.2f}, min: ${min_usd_size:.2f}, max: ${max_usd_size:.2f})"
            )

            return position_usd

        except Exception as e:
            logger.error(f"❌ Error calculating position size: {e}")
            return 0.0

    async def check_margin_safety(
        self,
        position_size_usd: float,
        current_positions: Dict[str, Any],
    ) -> bool:
        """
        Проверка безопасности маржи.

        Args:
            position_size_usd: Размер новой позиции
            current_positions: Текущие позиции

        Returns:
            bool: True если безопасно открывать
        """
        if not self.margin_monitor:
            return True

        try:
            return await self.margin_monitor.check_safety(
                position_size_usd, current_positions
            )
        except Exception as e:
            logger.error(f"❌ Error checking margin safety: {e}")
            return False

    async def check_liquidation_risk(
        self,
        symbol: str,
        side: str,
        position_size_usd: float,
        entry_price: float,
    ) -> bool:
        """
        Проверка риска ликвидации.

        Args:
            symbol: Торговый символ
            side: Сторона позиции
            position_size_usd: Размер позиции
            entry_price: Цена входа

        Returns:
            bool: True если риск приемлемый
        """
        if not self.liquidation_protector:
            return True

        try:
            return await self.liquidation_protector.check_risk(
                symbol, side, position_size_usd, entry_price
            )
        except Exception as e:
            logger.error(f"❌ Error checking liquidation risk: {e}")
            return False

    def get_adaptive_risk_params(
        self,
        balance: float,
        regime: Optional[str] = None,
        symbol: Optional[str] = None,
        signal_generator=None,
    ) -> Dict[str, Any]:
        """
        Получить адаптивные параметры риска.

        Делегирует в ConfigManager.

        Args:
            balance: Текущий баланс
            regime: Режим рынка
            symbol: Торговый символ
            signal_generator: Signal generator

        Returns:
            Dict: Параметры риска
        """
        return self.config_manager.get_adaptive_risk_params(
            balance, regime, symbol, signal_generator
        )
