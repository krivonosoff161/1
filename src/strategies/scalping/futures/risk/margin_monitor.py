"""
MarginMonitor - мониторинг маржи для Futures торговли.

TODO: Реализовать полную функциональность мониторинга маржи.
"""

import asyncio
import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger


class MarginMonitor:
    """
    Мониторинг маржи для Futures торговли.

    TODO: Реализовать проверку маржи на основе:
    - Текущего баланса
    - Использованной маржи
    - Доступной маржи
    - Уровня маржи (margin ratio)
    """

    def __init__(self, config: Optional[dict] = None):
        """
        Инициализация MarginMonitor.

        Args:
            config: Конфигурация мониторинга маржи (опционально)
        """
        self.config = config or {}
        # 🔴 BUG #22 FIX: TTL cache для маржи (5-15s TTL)
        self._margin_cache: Dict[str, Tuple[float, float, float]] = {}  # {symbol: (balance, used_margin, timestamp)}
        self._cache_ttl = 10.0  # 10 сек TTL

    def check_margin_available(
        self, required_margin: float, current_balance: float, used_margin: float
    ) -> tuple[bool, str]:
        """
        Проверяет доступность маржи для новой позиции.

        Args:
            required_margin: Требуемая маржа для новой позиции
            current_balance: Текущий баланс
            used_margin: Уже использованная маржа

        Returns:
            (allowed, reason) - можно ли открыть позицию и почему
        """
        available_margin = current_balance - used_margin

        if required_margin > available_margin:
            reason = (
                f"Недостаточно маржи: требуется {required_margin:.2f}, "
                f"доступно {available_margin:.2f}"
            )
            return False, reason

        reason = (
            f"✅ Маржа доступна: требуется {required_margin:.2f}, "
            f"доступно {available_margin:.2f}"
        )
        return True, reason

    def get_margin_ratio(self, current_balance: float, used_margin: float) -> float:
        """
        Вычисляет коэффициент использования маржи.

        Args:
            current_balance: Текущий баланс
            used_margin: Использованная маржа

        Returns:
            Коэффициент использования маржи (0.0 - 1.0)
        """
        if current_balance <= 0:
            return 1.0

        return min(1.0, used_margin / current_balance)

    async def check_safety(
        self,
        position_size_usd: float,
        current_positions: Dict[str, Any],
        orchestrator: Optional[Any] = None,  # ✅ Для доступа к балансу
        data_registry: Optional[Any] = None,  # ✅ Альтернативный источник данных
    ) -> bool:
        """
        ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (28.12.2025): Проверяет безопасность маржи перед открытием позиции.
        🔴 BUG #22 FIX (11.01.2026): Добавлена retry logic (2-3 попытки) + TTL cache (5-15s)

        Args:
            position_size_usd: Размер новой позиции в USD
            current_positions: Текущие позиции (для расчета общей маржи)
            orchestrator: Orchestrator для доступа к балансу (опционально)
            data_registry: DataRegistry для чтения баланса (опционально)

        Returns:
            bool: True если безопасно
        """
        try:
            cache_key = "margin_data"
            current_time = time.time()
            
            # ✅ Проверяем кэш (TTL 10s)
            if cache_key in self._margin_cache:
                cached_balance, cached_used_margin, cached_time = self._margin_cache[cache_key]
                if current_time - cached_time < self._cache_ttl:
                    logger.debug(f"📦 MarginMonitor: Using cached margin data (age={current_time-cached_time:.1f}s)")
                    return self._check_margin_safety(
                        position_size_usd, cached_balance, cached_used_margin
                    )
            
            # ✅ Получаем баланс и маржу с retry logic (2-3 попытки)
            current_balance = 0.0
            used_margin = 0.0
            
            # Retry configuration
            max_retries = 2
            retry_delays = [0.1, 0.2]  # 100ms, 200ms
            
            for attempt in range(max_retries + 1):
                try:
                    # Приоритет 1: Orchestrator
                    if orchestrator:
                        try:
                            if hasattr(orchestrator, "client") and orchestrator.client:
                                current_balance = await orchestrator.client.get_balance() or 0.0
                            if hasattr(orchestrator, "_get_used_margin"):
                                used_margin = await orchestrator._get_used_margin() or 0.0
                            
                            if current_balance > 0.0:
                                # ✅ Cache успешный результат
                                self._margin_cache[cache_key] = (current_balance, used_margin, current_time)
                                logger.debug(f"✅ MarginMonitor: Got balance from orchestrator (retry {attempt})")
                                return self._check_margin_safety(
                                    position_size_usd, current_balance, used_margin
                                )
                        except Exception as e:
                            logger.debug(
                                f"⚠️ MarginMonitor: Attempt {attempt} - Orchestrator failed: {e}"
                            )
                    
                    # Приоритет 2: DataRegistry (из orchestrator ~300)
                    if (current_balance == 0.0 or used_margin == 0.0) and data_registry:
                        try:
                            margin_data = await data_registry.get_margin()
                            balance_data = await data_registry.get_balance()
                            if margin_data:
                                used_margin = margin_data.get("used", 0.0)
                            if balance_data:
                                # ✅ ИСПРАВЛЕНО: DataRegistry.get_balance() возвращает {"balance": float, "profile": str, "updated_at": datetime}
                                # НЕ "equity" или "total"!
                                current_balance = balance_data.get("balance", 0.0)
                            
                            if current_balance > 0.0:
                                # ✅ Cache успешный результат
                                self._margin_cache[cache_key] = (current_balance, used_margin, current_time)
                                logger.debug(f"✅ MarginMonitor: Got balance from data_registry (retry {attempt})")
                                return self._check_margin_safety(
                                    position_size_usd, current_balance, used_margin
                                )
                        except Exception as e:
                            logger.debug(
                                f"⚠️ MarginMonitor: Attempt {attempt} - DataRegistry failed: {e}"
                            )
                    
                    # Если обе попытки не удались и есть еще retry - ждем перед следующей
                    if attempt < max_retries:
                        delay = retry_delays[attempt]
                        logger.debug(f"⏳ MarginMonitor: Retrying in {delay}s...")
                        await asyncio.sleep(delay)
                
                except Exception as e:
                    logger.debug(f"⚠️ MarginMonitor: Exception in retry loop (attempt {attempt}): {e}")
                    if attempt < max_retries:
                        delay = retry_delays[attempt]
                        await asyncio.sleep(delay)
            
            # ✅ Если у нас есть cached data и fresh sources недоступны - используем кэш
            if cache_key in self._margin_cache:
                cached_balance, cached_used_margin, cached_time = self._margin_cache[cache_key]
                logger.warning(
                    f"⚠️ MarginMonitor: Fresh data unavailable, using stale cache "
                    f"(age={(current_time-cached_time):.1f}s > TTL {self._cache_ttl}s)"
                )
                return self._check_margin_safety(
                    position_size_usd, cached_balance, cached_used_margin
                )
            
            # ✅ Если нет ни fresh ни cached data - блокируем
            logger.error(
                "❌ MarginMonitor: No balance data available after retries, blocking position"
            )
            return False
        
        except Exception as e:
            logger.error(f"❌ MarginMonitor: Error in check_safety: {e}", exc_info=True)
            return False
    
    def _check_margin_safety(
        self,
        position_size_usd: float,
        current_balance: float,
        used_margin: float
    ) -> bool:
        """
        Внутренняя функция для проверки безопасности маржи.
        🔴 BUG #22 FIX: Refactored из check_safety для переиспользования
        """
        try:
            # ✅ Рассчитываем требуемую маржу (с учетом leverage)
            # ✅ ИСПРАВЛЕНО (28.12.2025): RiskConfig не имеет метода .get(), используем getattr()
            if isinstance(self.config, dict):
                leverage = self.config.get("leverage", 5)
                max_margin_ratio = self.config.get("max_margin_ratio", 0.8)
            else:
                leverage = getattr(self.config, "leverage", 5)
                max_margin_ratio = getattr(self.config, "max_margin_ratio", 0.8)
            required_margin = position_size_usd / leverage

            # ✅ Проверяем доступность маржи
            available, reason = self.check_margin_available(
                required_margin, current_balance, used_margin
            )

            # ✅ Проверяем коэффициент использования маржи
            margin_ratio = self.get_margin_ratio(
                current_balance, used_margin + required_margin
            )

            if not available:
                logger.warning(f"❌ MarginMonitor: Margin unsafe: {reason}")
                return False

            if margin_ratio > max_margin_ratio:
                logger.warning(
                    f"❌ MarginMonitor: Margin ratio too high: {margin_ratio:.2%} > {max_margin_ratio:.2%} "
                    f"(balance=${current_balance:.2f}, used=${used_margin:.2f}, required=${required_margin:.2f})"
                )
                return False

            logger.debug(
                f"✅ MarginMonitor: Margin safe: ratio={margin_ratio:.2%} <= {max_margin_ratio:.2%}, "
                f"available=${current_balance - used_margin:.2f} >= required=${required_margin:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"❌ MarginMonitor: Error in _check_margin_safety: {e}", exc_info=True)
            return False
