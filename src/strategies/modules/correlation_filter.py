"""
Correlation Filter Module

Фильтрует торговые сигналы на основе корреляции между парами,
избегая одновременных позиций в сильно коррелированных активах.

Цель: Снизить портфельный риск путем диверсификации.
"""

from typing import Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field

from src.filters.correlation_manager import CorrelationConfig, CorrelationManager
from src.models import Position, PositionSide
from src.okx_client import OKXClient


class CorrelationFilterConfig(BaseModel):
    """Конфигурация Correlation фильтра"""

    enabled: bool = Field(default=True, description="Включить фильтр")

    max_correlated_positions: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Макс. кол-во позиций в коррелированных парах одновременно",
    )

    correlation_threshold: float = Field(
        default=0.7,
        ge=0.5,
        le=1.0,
        description="Порог высокой корреляции (>0.7 = блокируем)",
    )

    block_same_direction_only: bool = Field(
        default=True,
        description="Блокировать только если направления совпадают (LONG+LONG)",
    )


class CorrelationFilterResult(BaseModel):
    """Результат проверки Correlation фильтра"""

    allowed: bool = Field(description="Разрешен ли вход")
    blocked: bool = Field(description="Заблокирован ли вход")
    reason: str = Field(description="Причина решения")
    correlated_positions: List[str] = Field(
        default_factory=list, description="Список коррелированных открытых позиций"
    )
    correlation_values: Dict[str, float] = Field(
        default_factory=dict, description="Значения корреляций"
    )


class CorrelationFilter:
    """
    Фильтр корреляции для диверсификации портфеля.

    Блокирует вход в новую позицию, если уже есть открытые позиции
    в сильно коррелированных парах.

    Example:
        >>> config = CorrelationFilterConfig(correlation_threshold=0.7)
        >>> filter = CorrelationFilter(client, config, ["BTC-USDT", "ETH-USDT"])
        >>> result = await filter.check_entry(
        ...     "ETH-USDT", "LONG", current_positions
        ... )
        >>> if result.blocked:
        ...     logger.warning(f"Entry blocked: {result.reason}")
    """

    def __init__(
        self,
        client: OKXClient,
        config: CorrelationFilterConfig,
        all_symbols: List[str],
    ):
        """
        Инициализация Correlation фильтра.

        Args:
            client: OKX API клиент
            config: Конфигурация фильтра
            all_symbols: Все торгуемые символы
        """
        self.client = client
        self.config = config
        self.all_symbols = all_symbols

        # Инициализируем Correlation Manager
        corr_manager_config = CorrelationConfig(
            lookback_candles=100,
            timeframe="5m",
            cache_ttl_seconds=300,
            high_correlation_threshold=config.correlation_threshold,
        )
        self.correlation_manager = CorrelationManager(client, corr_manager_config)

        logger.info(
            f"Correlation Filter initialized: threshold={config.correlation_threshold}, "
            f"max_positions={config.max_correlated_positions}, "
            f"same_direction_only={config.block_same_direction_only}"
        )

    async def check_entry(
        self,
        symbol: str,
        signal_side: str,
        current_positions: Dict[str, Position],
    ) -> CorrelationFilterResult:
        """
        Проверить возможность входа с учетом корреляций.

        Args:
            symbol: Символ для входа
            signal_side: Направление сигнала ("LONG" или "SHORT")
            current_positions: Текущие открытые позиции {symbol: Position}

        Returns:
            CorrelationFilterResult с решением

        Example:
            >>> result = await filter.check_entry(
            ...     "ETH-USDT", "LONG", {"BTC-USDT": btc_position}
            ... )
            >>> if result.blocked:
            ...     logger.info(f"Blocked: {result.reason}")
        """
        if not self.config.enabled:
            return CorrelationFilterResult(
                allowed=True,
                blocked=False,
                reason="Correlation filter disabled",
            )

        # Если нет открытых позиций - разрешаем
        if not current_positions:
            return CorrelationFilterResult(
                allowed=True,
                blocked=False,
                reason="No open positions",
            )

        try:
            # Проверяем корреляции с открытыми позициями
            correlated_positions = []
            correlation_values = {}

            for open_symbol, position in current_positions.items():
                if open_symbol == symbol:
                    continue  # Пропускаем саму пару

                # Получаем корреляцию
                corr_data = await self.correlation_manager.get_correlation(
                    symbol, open_symbol
                )

                if not corr_data:
                    continue

                # Сохраняем значение корреляции
                correlation_values[open_symbol] = corr_data.correlation

                # Проверяем порог
                if abs(corr_data.correlation) >= self.config.correlation_threshold:
                    # Если включен фильтр по направлению
                    if self.config.block_same_direction_only:
                        # Блокируем только если направления совпадают
                        position_direction = (
                            "LONG"
                            if position.side == PositionSide.LONG
                            else "SHORT"
                        )
                        if signal_side == position_direction:
                            correlated_positions.append(open_symbol)
                            logger.debug(
                                f"Correlation Filter: {symbol} {signal_side} correlated with "
                                f"{open_symbol} {position_direction} ({corr_data.correlation:.2f})"
                            )
                    else:
                        # Блокируем независимо от направления
                        correlated_positions.append(open_symbol)
                        logger.debug(
                            f"Correlation Filter: {symbol} correlated with "
                            f"{open_symbol} ({corr_data.correlation:.2f})"
                        )

            # Проверяем лимит коррелированных позиций
            if len(correlated_positions) >= self.config.max_correlated_positions:
                logger.warning(
                    f"🚫 Correlation Filter BLOCKED: {symbol} {signal_side}\n"
                    f"   Correlated positions: {correlated_positions}\n"
                    f"   Correlations: {correlation_values}\n"
                    f"   Max allowed: {self.config.max_correlated_positions}"
                )
                return CorrelationFilterResult(
                    allowed=False,
                    blocked=True,
                    reason=f"Too many correlated positions ({len(correlated_positions)}/{self.config.max_correlated_positions})",
                    correlated_positions=correlated_positions,
                    correlation_values=correlation_values,
                )

            # Разрешаем вход
            if correlated_positions:
                logger.info(
                    f"✅ Correlation Filter ALLOWED: {symbol} {signal_side}\n"
                    f"   Correlated: {correlated_positions} (within limit)\n"
                    f"   Correlations: {correlation_values}"
                )
            else:
                logger.info(
                    f"✅ Correlation Filter ALLOWED: {symbol} {signal_side} (no correlations)"
                )

            return CorrelationFilterResult(
                allowed=True,
                blocked=False,
                reason=f"Correlated positions: {len(correlated_positions)}/{self.config.max_correlated_positions}",
                correlated_positions=correlated_positions,
                correlation_values=correlation_values,
            )

        except Exception as e:
            logger.error(
                f"Correlation Filter error for {symbol}: {e}", exc_info=True
            )
            # При ошибке разрешаем (fail-safe)
            return CorrelationFilterResult(
                allowed=True,
                blocked=False,
                reason=f"Error (fail-safe): {str(e)}",
            )

    async def preload_correlations(self):
        """
        Предзагрузить все корреляции между символами.

        Полезно вызвать при старте бота для заполнения кэша.
        """
        logger.info("Preloading correlations for all symbols...")
        correlations = await self.correlation_manager.get_all_correlations(
            self.all_symbols
        )
        logger.info(f"Preloaded {len(correlations)} correlations")

        # Логируем сильные корреляции
        for (pair1, pair2), corr_data in correlations.items():
            if corr_data.is_strong:
                logger.info(
                    f"  Strong correlation: {pair1}/{pair2} = {corr_data.correlation:.3f}"
                )

    def get_stats(self) -> Dict:
        """Получить статистику фильтра"""
        cache_stats = self.correlation_manager.get_cache_stats()
        return {
            "enabled": self.config.enabled,
            "threshold": self.config.correlation_threshold,
            "max_positions": self.config.max_correlated_positions,
            **cache_stats,
        }

