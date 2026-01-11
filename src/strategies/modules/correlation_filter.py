"""
Correlation Filter Module

Фильтрует торговые сигналы на основе корреляции между парами,
избегая одновременных позиций в сильно коррелированных активах.

Цель: Снизить портфельный риск путем диверсификации.
"""

import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from loguru import logger
from pydantic import BaseModel, Field

from src.clients.spot_client import OKXClient
from src.filters.correlation_manager import (CorrelationConfig,
                                             CorrelationManager)
from src.models import Position, PositionSide


class CorrelationFilterConfig(BaseModel):
    """Конфигурация Correlation фильтра"""

    enabled: bool = Field(default=True, description="Включить фильтр")

    max_correlated_positions: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Макс. кол-во позиций в коррелированных парах одновременно (в одном направлении)",
    )

    correlation_threshold: float = Field(
        default=0.8,
        ge=0.5,
        le=1.0,
        description="Порог высокой корреляции (>0.8 = предупреждение, не блок)",
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
        data_registry=None,
    ):
        """
        Инициализация Correlation фильтра.

        Args:
            client: OKX API клиент
            config: Конфигурация фильтра
            all_symbols: Все торгуемые символы
            data_registry: DataRegistry для получения свечей (опционально, приоритет над API)
        """
        self.client = client
        self.config = config
        self.all_symbols = all_symbols
        self.data_registry = data_registry  # ✅ КРИТИЧЕСКОЕ: Сохраняем DataRegistry

        # Инициализируем Correlation Manager с DataRegistry
        corr_manager_config = CorrelationConfig(
            lookback_candles=100,
            timeframe="5m",
            cache_ttl_seconds=300,
            high_correlation_threshold=config.correlation_threshold,
        )
        self.correlation_manager = CorrelationManager(
            client, corr_manager_config, data_registry=self.data_registry
        )  # ✅ КРИТИЧЕСКОЕ: Передаем DataRegistry

        # Динамическая статистика блокировок для адаптации порога
        self._decision_history: Deque[Tuple[float, bool]] = deque(maxlen=120)
        self._temporary_relax_signals_remaining: int = 0
        self._temporary_threshold_delta: float = 0.0

        logger.info(
            f"Correlation Filter initialized: threshold={config.correlation_threshold}, "
            f"max_positions={config.max_correlated_positions}, "
            f"same_direction_only={config.block_same_direction_only}"
        )

    def update_parameters(self, new_config: CorrelationFilterConfig):
        """
        Обновить параметры Correlation Filter (при переключении режима ARM).

        Args:
            new_config: Новая конфигурация
        """
        old_threshold = self.config.correlation_threshold
        old_max = self.config.max_correlated_positions

        self.config = new_config

        # Обновляем порог в CorrelationManager
        self.correlation_manager.config.high_correlation_threshold = (
            new_config.correlation_threshold
        )

        logger.info(
            f"🔄 Correlation Filter параметры обновлены:\n"
            f"   threshold: {old_threshold} → {new_config.correlation_threshold}\n"
            f"   max_positions: {old_max} → {new_config.max_correlated_positions}"
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

            threshold = self._get_effective_threshold()
            self.correlation_manager.config.high_correlation_threshold = threshold

            for open_symbol, position in current_positions.items():
                if open_symbol == symbol:
                    continue  # Пропускаем саму пару

                # Получаем корреляцию
                corr_data = await self.correlation_manager.get_correlation(
                    symbol, open_symbol
                )

                if not corr_data:
                    continue

                # ✅ ИСПРАВЛЕНИЕ: Безопасное извлечение correlation
                # corr_data может быть CorrelationData (Pydantic модель) или словарем
                if isinstance(corr_data, dict):
                    correlation_value = corr_data.get("correlation", 0.0)
                else:
                    # CorrelationData объект
                    correlation_value = getattr(corr_data, "correlation", 0.0)

                # Сохраняем значение корреляции
                correlation_values[open_symbol] = correlation_value

                # Проверяем порог (используем безопасно извлеченное значение)
                if abs(correlation_value) >= threshold:
                    # Если включен фильтр по направлению
                    if self.config.block_same_direction_only:
                        # Блокируем только если направления совпадают
                        # ✅ ИСПРАВЛЕНИЕ: position может быть словарем (из API) или объектом Position
                        if isinstance(position, dict):
                            # Из API: "pos" > 0 = LONG, < 0 = SHORT
                            pos_size = float(position.get("pos", "0"))
                            position_direction = "LONG" if pos_size > 0 else "SHORT"
                        else:
                            # Объект Position
                            position_direction = (
                                "LONG"
                                if position.side == PositionSide.LONG
                                else "SHORT"
                            )
                        if signal_side == position_direction:
                            correlated_positions.append(open_symbol)
                            logger.debug(
                                f"Correlation Filter: {symbol} {signal_side} correlated with "
                                f"{open_symbol} {position_direction} ({correlation_value:.2f})"
                            )
                    else:
                        # Блокируем независимо от направления
                        correlated_positions.append(open_symbol)
                        logger.debug(
                            f"Correlation Filter: {symbol} correlated with "
                            f"{open_symbol} ({correlation_value:.2f})"
                        )

            # Проверяем лимит коррелированных позиций
            if len(correlated_positions) >= self.config.max_correlated_positions:
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (08.01.2026): Проверяем противоположные направления (хедж)
                # Если есть позиции в противоположном направлении → разрешаем (хеджирование)
                opposite_positions = []
                for pos_symbol in correlated_positions:
                    pos = current_positions[pos_symbol]
                    if isinstance(pos, dict):
                        pos_size = float(pos.get("pos", "0"))
                        pos_direction = "LONG" if pos_size > 0 else "SHORT"
                    else:
                        pos_direction = (
                            "LONG" if pos.side == PositionSide.LONG else "SHORT"
                        )
                    
                    if signal_side != pos_direction:
                        opposite_positions.append(pos_symbol)
                
                if len(opposite_positions) > 0:
                    logger.info(
                        f"✅ Correlation Filter ALLOWED: {symbol} {signal_side} — хедж для "
                        f"{len(opposite_positions)} противоположных позиций: {opposite_positions}"
                    )
                    return CorrelationFilterResult(
                        allowed=True,
                        blocked=False,
                        reason=f"Хеджирование: {len(opposite_positions)} противоположных позиций",
                        correlated_positions=opposite_positions,
                        correlation_values=correlation_values,
                    )
                
                # ✅ СМЯГЧЕНО (11.01.2026): вместо BLOCKED → WARNING, разрешаем вход (мягкий фильтр)
                logger.warning(
                    f"⚠️ Correlation Filter WARNING: {symbol} {signal_side} — много коррелированных позиций\n"
                    f"   Correlated positions: {correlated_positions}\n"
                    f"   Correlations: {correlation_values}\n"
                    f"   Threshold: {threshold:.2f}\n"
                    f"   Max allowed: {self.config.max_correlated_positions} (но разрешаем - мягкий фильтр)"
                )
                self._record_decision(blocked=False)
                return CorrelationFilterResult(
                    allowed=True,
                    blocked=False,
                    reason=f"WARNING: {len(correlated_positions)} correlated positions (soft limit, allowed)",
                    correlated_positions=correlated_positions,
                    correlation_values=correlation_values,
                )

            # ✅ ИСПРАВЛЕНО (08.01.2026): ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА - блокировать даже одну коррелированную позицию
            # если корреляция очень высокая (> 0.85) и направления совпадают
            if correlated_positions and not self.config.block_same_direction_only:
                # Если mode НЕ "блокировать только по направлению", то используем дефолт - не пропускаем
                logger.warning(
                    f"🚫 Correlation Filter BLOCKED (HIGH_CORRELATION): {symbol} {signal_side}\n"
                    f"   Correlated positions: {correlated_positions}\n"
                    f"   Correlations: {correlation_values}\n"
                    f"   Threshold: {threshold:.2f}"
                )
                self._record_decision(blocked=True)
                return CorrelationFilterResult(
                    allowed=False,
                    blocked=True,
                    reason=f"Correlated with open positions: {correlated_positions}",
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

            self._record_decision(blocked=False)
            return CorrelationFilterResult(
                allowed=True,
                blocked=False,
                reason=f"Correlated positions: {len(correlated_positions)}/{self.config.max_correlated_positions} (threshold={threshold:.2f})",
                correlated_positions=correlated_positions,
                correlation_values=correlation_values,
            )

        except Exception as e:
            logger.error(f"Correlation Filter error for {symbol}: {e}", exc_info=True)
            # При ошибке разрешаем (fail-safe)
            return CorrelationFilterResult(
                allowed=True,
                blocked=False,
                reason=f"Error (fail-safe): {str(e)}",
            )

    def _get_effective_threshold(self) -> float:
        """
        Возвращает актуальный порог корреляции с учетом временной релаксации.
        """
        threshold = self.config.correlation_threshold
        if self._temporary_relax_signals_remaining > 0:
            threshold = max(0.5, threshold - self._temporary_threshold_delta)
            self._temporary_relax_signals_remaining -= 1
            if self._temporary_relax_signals_remaining == 0:
                self._temporary_threshold_delta = 0.0
        return threshold

    def _record_decision(self, blocked: bool) -> None:
        """
        Запоминает решение фильтра и при избыточных блокировках временно снижает порог.
        """
        now = time.time()
        self._decision_history.append((now, blocked))

        cutoff = now - 600  # 10 минут
        while self._decision_history and self._decision_history[0][0] < cutoff:
            self._decision_history.popleft()

        total = len(self._decision_history)
        if blocked and total >= 5 and self._temporary_relax_signals_remaining == 0:
            blocked_count = sum(
                1 for _, is_blocked in self._decision_history if is_blocked
            )
            block_rate = blocked_count / total if total else 0.0
            if block_rate >= 0.6:
                self._temporary_relax_signals_remaining = 3
                self._temporary_threshold_delta = 0.1
                logger.debug(
                    f"🔓 CorrelationFilter: временно снижаем порог на 0.05 для следующих 3 сигналов "
                    f"(blocked_rate={block_rate:.1%}, window={total})"
                )
                # Сбрасываем статистику, чтобы не триггерить повторно сразу
                self._decision_history.clear()

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

    async def is_signal_valid(self, signal: Dict, market_data=None) -> bool:
        """
        Проверка валидности сигнала через Correlation фильтр.

        Args:
            signal: Торговый сигнал (должен содержать "symbol" и "side" как "buy"/"sell")
            market_data: Рыночные данные (не используются)

        Returns:
            bool: True если сигнал валиден, False если заблокирован
        """
        try:
            if not self.config.enabled:
                return True  # Фильтр отключен - разрешаем все

            symbol = signal.get("symbol")
            signal_side = signal.get("side")  # "buy" или "sell"

            if not symbol or not signal_side:
                logger.warning(f"Correlation: Неполный сигнал для проверки: {signal}")
                return True  # Fail-open: если нет данных - разрешаем

            # Конвертируем side в формат CorrelationFilter ("buy" -> "LONG", "sell" -> "SHORT")
            signal_side_long = "LONG" if signal_side == "buy" else "SHORT"

            # Получаем текущие открытые позиции из signal (если переданы)
            # Если позиции не переданы - CorrelationFilter не может работать корректно
            # В этом случае разрешаем сигнал (fail-open)
            current_positions = signal.get("current_positions", {})

            # Если позиции не переданы - не можем проверить корреляцию
            # В этом случае разрешаем сигнал (фильтр не активен без позиций)
            # TODO: В будущем можно получать позиции из position_manager через callback

            # Проверяем через check_entry
            result = await self.check_entry(
                symbol=symbol,
                signal_side=signal_side_long,
                current_positions=current_positions,
            )

            # Если заблокирован - возвращаем False
            if result.blocked:
                logger.debug(
                    f"🔍 CorrelationFilter заблокировал сигнал {symbol} {signal_side_long}: {result.reason}"
                )
                return False

            # Если разрешен - возвращаем True
            return True

        except Exception as e:
            logger.warning(
                f"⚠️ Ошибка проверки CorrelationFilter для сигнала: {e}, "
                f"разрешаем сигнал (fail-open)"
            )
            return True  # Fail-open: при ошибке разрешаем сигнал

    def get_stats(self) -> Dict:
        """Получить статистику фильтра"""
        cache_stats = self.correlation_manager.get_cache_stats()
        return {
            "enabled": self.config.enabled,
            "threshold": self.config.correlation_threshold,
            "max_positions": self.config.max_correlated_positions,
            **cache_stats,
        }
