"""
Risk Manager для Futures торговли.

Ответственность:
- Расчет размера позиции с учетом баланса и режима
- Проверка безопасности маржи
- Интеграция с ConfigManager
- Интеграция с существующими risk модулями
- ✅ FIX: Circuit breaker для серии убытков
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig

from .config.config_manager import ConfigManager
from .config.config_view import get_scalping_view
from .risk.liquidation_protector import LiquidationProtector
from .risk.margin_monitor import MarginMonitor
from .risk.max_size_limiter import MaxSizeLimiter
from .utils.units import pct_points_to_fraction


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
        orchestrator: Optional[Any] = None,
        data_registry=None,  # ✅ НОВОЕ: DataRegistry для чтения баланса
    ):
        """
        Args:
            config: Конфигурация бота
            client: Futures клиент
            config_manager: Config Manager
            liquidation_protector: Защита от ликвидации (опционально)
            margin_monitor: Мониторинг маржи (опционально)
            max_size_limiter: Ограничитель размера (опционально)
            orchestrator: Ссылка на orchestrator для доступа к методам (опционально)
            data_registry: DataRegistry для чтения баланса (опционально)
        """
        self.config = config
        self.scalping_config = get_scalping_view(config)
        self.risk_config = config.risk
        self.client = client
        self.config_manager = config_manager
        self.liquidation_protector = liquidation_protector
        self.margin_monitor = margin_monitor
        self.max_size_limiter = max_size_limiter
        self.orchestrator = (
            orchestrator  # ✅ РЕФАКТОРИНГ: Для доступа к методам orchestrator
        )
        # ✅ НОВОЕ: DataRegistry для чтения баланса
        self.data_registry = data_registry

        # Получаем symbol_profiles из config_manager
        self.symbol_profiles = config_manager.get_symbol_profiles()

        # ✅ FIX: Circuit breaker для серии убытков - АДАПТИВНО из конфига
        self.pair_loss_streak: Dict[str, int] = {}  # symbol → кол-во убытков подряд
        self.pair_block_until: Dict[
            str, float
        ] = {}  # symbol → monotonic time до которого блок

        # ✅ FIX: Читаем из конфига, не хард-код
        self._max_consecutive_losses = (
            getattr(self.risk_config, "consecutive_losses_limit", None) or 5
        )
        self._block_duration_minutes = (
            getattr(self.risk_config, "pair_block_duration_min", None) or 30
        )

        # ✅ НОВОЕ: Отслеживание дневного PnL для max_daily_loss
        self.daily_pnl: float = 0.0  # Текущий дневной PnL
        self.daily_pnl_date: Optional[str] = None  # Дата текущего дня (YYYY-MM-DD)
        self.max_daily_loss_percent: float = (
            getattr(self.risk_config, "max_daily_loss_percent", None) or 5.0
        )  # Максимальная дневная потеря в % от баланса
        self.daily_trading_stopped: bool = False  # Флаг остановки торговли

        logger.info(
            f"ADAPT_LOAD consecutive_losses_limit={self._max_consecutive_losses}"
        )
        logger.info(
            f"ADAPT_LOAD pair_block_duration_min={self._block_duration_minutes}"
        )
        logger.info("✅ FuturesRiskManager initialized")

    def _get_symbol_regime_profile(
        self, symbol: Optional[str], regime: Optional[str]
    ) -> Dict[str, Any]:
        """Вспомогательный метод для получения regime_profile (аналог orchestrator._get_symbol_regime_profile)"""
        if not symbol:
            return {}
        profile = self.symbol_profiles.get(symbol, {})
        if not profile:
            return {}
        if regime:
            symbol_dict = (
                self.config_manager.to_dict(profile)
                if not isinstance(profile, dict)
                else profile
            )
            return symbol_dict.get(regime.lower(), {})
        return {}

    def _resolve_sl_percent_for_risk(
        self, symbol: Optional[str], regime: Optional[str]
    ) -> float:
        """Надёжно получить sl_percent для риск-расчётов (в процентах, не доле)."""
        # 1) Из scalping_config (если задан)
        sl_percent = getattr(self.scalping_config, "sl_percent", None)
        if sl_percent is not None:
            return float(sl_percent)

        # 2) Из exit_params (централизованные параметры выходов)
        try:
            raw = getattr(self.config_manager, "_raw_config_dict", {}) or {}
            exit_params = raw.get("exit_params") or {}
            regime_key = (regime or "ranging").lower()
            sl_percent = (exit_params.get(regime_key) or {}).get("sl_min_percent")
            if sl_percent is not None:
                return float(sl_percent)
        except Exception:
            pass

        # 3) Из symbol_profiles по режиму (если задан)
        if symbol:
            regime_profile = self._get_symbol_regime_profile(symbol, regime)
            sl_percent = regime_profile.get("sl_percent")
            if sl_percent is not None:
                return float(sl_percent)

        raise ValueError(
            "sl_percent отсутствует: проверь config_futures.yaml (scalping.sl_percent или exit_params.<regime>.sl_min_percent)"
        )

    async def _get_used_margin(self) -> float:
        """Получает использованную маржу через orchestrator или напрямую"""
        if self.orchestrator and hasattr(self.orchestrator, "_get_used_margin"):
            return await self.orchestrator._get_used_margin()
        # Fallback: получаем напрямую
        try:
            exchange_positions = await self.client.get_positions()
            if not exchange_positions:
                return 0.0
            total_margin = 0.0
            for pos in exchange_positions:
                try:
                    pos_size = float(pos.get("pos", "0") or 0)
                except (TypeError, ValueError):
                    pos_size = 0.0
                if abs(pos_size) < 1e-8:
                    continue
                try:
                    margin = float(pos.get("margin", "0") or 0)
                    total_margin += margin
                except (TypeError, ValueError):
                    continue
            return total_margin
        except Exception as e:
            logger.warning(f"⚠️ Ошибка получения used_margin: {e}")
            return 0.0

    def _calculate_dynamic_margin_cap(
        self,
        balance: float,
        symbol: str,
        regime: str,
        volatility: Optional[float] = None,
        daily_pnl: float = 0.0,
        open_positions_margin: float = 0.0,
    ) -> float:
        """
        Динамический расчет максимальной маржи на сделку.

        Учитывает:
        - max_margin_per_trade из конфига
        - Волатильность (ATR)
        - Просадку портфеля
        - Режим рынка

        Args:
            balance: Текущий баланс
            symbol: Торговый символ
            regime: Режим рынка (trending, ranging, choppy)
            volatility: Волатильность (ATR % от цены, опционально)
            daily_pnl: Дневной PnL (для расчета просадки)
            open_positions_margin: Использованная маржа открытых позиций

        Returns:
            Максимальная маржа на сделку в USD
        """
        try:
            # Получаем параметры из конфига
            risk_config = getattr(self.scalping_config, "risk_config", {})
            if isinstance(risk_config, dict):
                max_margin_per_trade_pct = (
                    risk_config.get("max_margin_per_trade", 15.0) / 100.0
                )
                volatility_factor_enabled = risk_config.get(
                    "volatility_factor_enabled", True
                )
                drawdown_factor_enabled = risk_config.get(
                    "drawdown_factor_enabled", True
                )
                min_margin_cap = risk_config.get("min_margin_cap", 8.0)
                max_margin_cap_multiplier = risk_config.get(
                    "max_margin_cap_multiplier", 2.0
                )
            else:
                max_margin_per_trade_pct = (
                    getattr(risk_config, "max_margin_per_trade", 15.0) / 100.0
                )
                volatility_factor_enabled = getattr(
                    risk_config, "volatility_factor_enabled", True
                )
                drawdown_factor_enabled = getattr(
                    risk_config, "drawdown_factor_enabled", True
                )
                min_margin_cap = getattr(risk_config, "min_margin_cap", 8.0)
                max_margin_cap_multiplier = getattr(
                    risk_config, "max_margin_cap_multiplier", 2.0
                )

            # Базовый кап = баланс * процент
            base_cap = balance * max_margin_per_trade_pct

            # Фактор волатильности (чем выше волатильность, тем меньше кап)
            volatility_factor = 1.0
            if volatility_factor_enabled and volatility is not None and volatility > 0:
                # Нормализуем волатильность: 1% = 1.0, 2% = 0.5, 3% = 0.33
                # Используем обратную зависимость: factor = 1 / (1 + volatility)
                volatility_factor = 1.0 / (
                    1.0 + volatility * 10
                )  # Умножаем на 10 для усиления эффекта
                volatility_factor = max(
                    0.5, min(1.5, volatility_factor)
                )  # Ограничиваем 0.5-1.5

            # Фактор просадки (чем больше просадка, тем меньше кап)
            drawdown_factor = 1.0
            if drawdown_factor_enabled and daily_pnl < 0:
                # Просадка уменьшает кап: -5% = 0.5, -10% = 0.0
                drawdown_pct = abs(daily_pnl) / balance if balance > 0 else 0.0
                drawdown_factor = max(
                    0.0, 1.0 - drawdown_pct * 2
                )  # Усиливаем эффект просадки
                drawdown_factor = max(
                    0.3, min(1.0, drawdown_factor)
                )  # Минимум 30% от базового капа

            # Режимный множитель (trending = больше, choppy = меньше)
            regime_multiplier = 1.0
            if regime:
                regime_lower = regime.lower()
                if regime_lower == "trending":
                    regime_multiplier = 1.2  # +20% в тренде
                elif regime_lower == "ranging":
                    regime_multiplier = 1.0  # Стандарт
                elif regime_lower == "choppy":
                    regime_multiplier = 0.8  # -20% в хаосе

            # Рассчитываем динамический кап
            dynamic_cap = (
                base_cap * volatility_factor * drawdown_factor * regime_multiplier
            )

            # Применяем ограничения
            min_cap = min_margin_cap
            max_cap = base_cap * max_margin_cap_multiplier

            final_cap = max(min_cap, min(dynamic_cap, max_cap))

            logger.debug(
                f"📊 Dynamic Margin Cap для {symbol} ({regime}): "
                f"base=${base_cap:.2f}, vol_factor={volatility_factor:.2f}, "
                f"drawdown_factor={drawdown_factor:.2f}, regime_mult={regime_multiplier:.2f}, "
                f"final=${final_cap:.2f}"
            )

            return final_cap

        except Exception as e:
            logger.warning(f"⚠️ Ошибка расчета dynamic_margin_cap: {e}")
            # Fallback: возвращаем базовый кап
            risk_config = getattr(self.scalping_config, "risk_config", {})
            if isinstance(risk_config, dict):
                max_margin_per_trade_pct = (
                    risk_config.get("max_margin_per_trade", 15.0) / 100.0
                )
            else:
                max_margin_per_trade_pct = (
                    getattr(risk_config, "max_margin_per_trade", 15.0) / 100.0
                )
            return balance * max_margin_per_trade_pct

    async def calculate_max_margin_per_position(
        self,
        balance: float,
        balance_profile: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> float:
        """
        Рассчитать максимальную маржу на одну позицию.

        Используется для проверки лимитов при добавлении к позиции.
        Учитывает баланс, профиль баланса и режим рынка.

        Args:
            balance: Текущий баланс
            balance_profile: Профиль баланса (small, medium, large)
            regime: Режим рынка (trending, ranging, choppy)

        Returns:
            Максимальная маржа на позицию в USD
        """
        try:
            # Базовый процент по профилю баланса
            if balance_profile == "small":
                base_percent = 0.15  # 15% для малого баланса
            elif balance_profile == "medium":
                base_percent = 0.20  # 20% для среднего баланса
            elif balance_profile == "large":
                base_percent = 0.25  # 25% для большого баланса
            else:
                # Fallback: используем средний профиль
                base_percent = 0.20
                logger.debug(
                    f"⚠️ Неизвестный balance_profile={balance_profile}, используем 20%"
                )

            # Корректировка по режиму рынка
            regime_multiplier = 1.0
            if regime == "trending":
                regime_multiplier = 1.05  # +5% в тренде (можно больше)
            elif regime == "choppy":
                regime_multiplier = 0.95  # -5% в хаосе (меньше риска)
            # ranging: 1.0 (без изменений)

            max_margin_per_position = balance * base_percent * regime_multiplier

            logger.debug(
                f"📊 [MAX_MARGIN_PER_POSITION] balance=${balance:.2f}, "
                f"profile={balance_profile}, regime={regime}, "
                f"base_percent={base_percent*100:.1f}%, "
                f"regime_multiplier={regime_multiplier}, "
                f"max_margin=${max_margin_per_position:.2f}"
            )

            return max_margin_per_position

        except Exception as e:
            logger.error(
                f"❌ Ошибка расчета max_margin_per_position: {e}", exc_info=True
            )
            # Fallback: 20% от баланса
            return balance * 0.20

    def _calculate_risk_based_margin(
        self,
        balance: float,
        risk_per_trade: float,
        sl_distance_pct: float,
        leverage: int,
        price: float,
    ) -> float:
        """
        Расчет маржи через risk_usd / sl_distance (Уровень 3: Margin Budget).

        Формула:
        risk_usd = balance * risk_per_trade
        size_coins = risk_usd / sl_distance_pct
        margin_usd = (size_coins * price) / leverage

        Args:
            balance: Текущий баланс
            risk_per_trade: Риск на сделку в процентах (например, 0.012 = 1.2%)
            sl_distance_pct: Расстояние до SL в процентах (например, 0.02 = 2%)
            leverage: Плечо
            price: Текущая цена

        Returns:
            Маржа в USD
        """
        try:
            if sl_distance_pct <= 0 or leverage <= 0 or price <= 0:
                logger.warning(
                    f"⚠️ Risk-based margin: невалидные параметры "
                    f"(sl_distance={sl_distance_pct}, leverage={leverage}, price={price})"
                )
                return 0.0

            # Рассчитываем риск в USD
            risk_usd = balance * risk_per_trade

            # Рассчитываем размер позиции в монетах через риск
            # Если SL = 2%, то при убытке 2% мы потеряем risk_usd
            # Значит: size_coins * price * sl_distance_pct = risk_usd
            # size_coins = risk_usd / (price * sl_distance_pct)
            size_coins = risk_usd / (price * sl_distance_pct)

            # Рассчитываем номинальную стоимость
            notional_usd = size_coins * price

            # Рассчитываем маржу
            margin_usd = notional_usd / leverage

            logger.debug(
                f"📊 Risk-based Margin: risk_usd=${risk_usd:.2f}, "
                f"sl_distance={sl_distance_pct*100:.2f}%, size_coins={size_coins:.6f}, "
                f"notional=${notional_usd:.2f}, margin=${margin_usd:.2f}"
            )

            return margin_usd

        except Exception as e:
            logger.warning(f"⚠️ Ошибка расчета risk_based_margin: {e}")
            return 0.0

    async def _check_drawdown_protection(self) -> bool:
        """Проверяет drawdown protection через orchestrator"""
        if self.orchestrator and hasattr(
            self.orchestrator, "_check_drawdown_protection"
        ):
            return await self.orchestrator._check_drawdown_protection()
        return True  # Если orchestrator не доступен, разрешаем торговлю

    async def _check_emergency_stop_unlock(self):
        """Проверяет emergency stop unlock через orchestrator"""
        if self.orchestrator and hasattr(
            self.orchestrator, "_check_emergency_stop_unlock"
        ):
            return await self.orchestrator._check_emergency_stop_unlock()

    # ✅ FIX: Circuit breaker методы для серии убытков
    def record_trade_result(
        self,
        symbol: str,
        is_profit: bool,
        error_code: Optional[str] = None,
        error_msg: Optional[str] = None,
    ):
        """
        Записывает результат сделки для circuit breaker.
        Вызывать после закрытия каждой сделки.

        Args:
            symbol: Торговый символ
            is_profit: True если прибыль, False если убыток
            error_code: Код ошибки (например, "51169") - для фильтрации технических ошибок
            error_msg: Сообщение об ошибке - для дополнительной проверки
        """
        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Не считаем технические ошибки (51169) как убытки
        # Ошибка 51169 = "Order failed because you don't have any positions to reduce"
        # Это техническая ошибка, а не убыток от рынка
        if not is_profit and (
            error_code == "51169"
            or (error_msg and "don't have any positions" in error_msg.lower())
        ):
            logger.debug(
                f"⚠️ Техническая ошибка {error_code} для {symbol} не считается убытком для PAIR_BLOCK"
            )
            return  # Не записываем как убыток

        if is_profit:
            # Сбрасываем серию при прибыли
            if symbol in self.pair_loss_streak:
                old_streak = self.pair_loss_streak[symbol]
                if old_streak > 0:
                    logger.info(
                        f"PAIR_STREAK_RESET {symbol}: {old_streak} → 0 (profit)"
                    )
            self.pair_loss_streak[symbol] = 0
        else:
            # Увеличиваем серию при убытке
            self.pair_loss_streak[symbol] = self.pair_loss_streak.get(symbol, 0) + 1
            streak = self.pair_loss_streak[symbol]

            if streak < self._max_consecutive_losses:
                logger.info(
                    f"PAIR_STREAK {symbol} {streak}/{self._max_consecutive_losses}"
                )
            else:
                # Блокируем пару
                block_until = time.monotonic() + (self._block_duration_minutes * 60)
                self.pair_block_until[symbol] = block_until
                logger.critical(
                    f"PAIR_BLOCK {symbol} {streak}/{self._max_consecutive_losses} "
                    f"→ blocked for {self._block_duration_minutes} min"
                )

    def get_consecutive_losses(self, symbol: str) -> int:
        """Получить количество последовательных убытков для символа."""
        return self.pair_loss_streak.get(symbol, 0)

    def is_symbol_blocked(self, symbol: str) -> bool:
        """Проверяет, заблокирован ли символ из-за серии убытков."""
        if symbol not in self.pair_block_until:
            return False

        block_until = self.pair_block_until[symbol]
        if time.monotonic() >= block_until:
            # Блокировка истекла - сбрасываем
            del self.pair_block_until[symbol]
            self.pair_loss_streak[symbol] = 0
            logger.info(f"PAIR_UNBLOCK {symbol}: block expired, streak reset")
            return False

        # Блокировка активна
        remaining = (block_until - time.monotonic()) / 60
        logger.debug(f"PAIR_BLOCKED {symbol}: {remaining:.1f} min remaining")
        return True

    async def _check_max_daily_loss(self, balance: float) -> bool:
        """
        Проверка максимальной дневной потери.

        Args:
            balance: Текущий баланс

        Returns:
            True если торговля разрешена, False если превышен лимит
        """
        try:
            # Получаем текущую дату
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Если дата изменилась, сбрасываем дневной PnL
            if self.daily_pnl_date != current_date:
                logger.info(
                    f"📅 Новый торговый день: {current_date}. "
                    f"Сбрасываем дневной PnL (было: ${self.daily_pnl:.2f})"
                )
                self.daily_pnl = 0.0
                self.daily_pnl_date = current_date
                self.daily_trading_stopped = False

            # Если торговля уже остановлена, проверяем не нужно ли разблокировать
            if self.daily_trading_stopped:
                # Проверяем, не восстановился ли баланс
                max_daily_loss_usd = balance * (self.max_daily_loss_percent / 100.0)
                if self.daily_pnl >= -max_daily_loss_usd:
                    logger.info(
                        f"✅ Дневной PnL восстановился: ${self.daily_pnl:.2f} >= "
                        f"-${max_daily_loss_usd:.2f}. Возобновляем торговлю"
                    )
                    self.daily_trading_stopped = False
                else:
                    logger.warning(
                        f"⛔ Торговля остановлена из-за превышения max_daily_loss: "
                        f"PnL=${self.daily_pnl:.2f}, лимит=-${max_daily_loss_usd:.2f} "
                        f"({self.max_daily_loss_percent}% от баланса ${balance:.2f})"
                    )
                    return False

            # Проверяем текущий дневной PnL
            max_daily_loss_usd = balance * (self.max_daily_loss_percent / 100.0)
            if self.daily_pnl <= -max_daily_loss_usd:
                logger.error(
                    f"❌ ПРЕВЫШЕН MAX_DAILY_LOSS: PnL=${self.daily_pnl:.2f} <= "
                    f"-${max_daily_loss_usd:.2f} ({self.max_daily_loss_percent}% от баланса ${balance:.2f})"
                )
                self.daily_trading_stopped = True
                return False

            return True

        except Exception as e:
            logger.error(
                f"❌ Ошибка проверки max_daily_loss: {e}",
                exc_info=True,
            )
            # При ошибке разрешаем торговлю (безопаснее)
            return True

    def record_daily_pnl(self, pnl: float):
        """
        Записывает PnL сделки в дневной PnL.

        Args:
            pnl: PnL сделки (может быть отрицательным)
        """
        try:
            # Получаем текущую дату
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Если дата изменилась, сбрасываем дневной PnL
            if self.daily_pnl_date != current_date:
                logger.info(
                    f"📅 Новый торговый день: {current_date}. "
                    f"Сбрасываем дневной PnL (было: ${self.daily_pnl:.2f})"
                )
                self.daily_pnl = 0.0
                self.daily_pnl_date = current_date
                self.daily_trading_stopped = False

            # Добавляем PnL сделки
            self.daily_pnl += pnl

            logger.debug(
                f"📊 Дневной PnL обновлен: ${self.daily_pnl:.2f} "
                f"(добавлено: ${pnl:.2f})"
            )

        except Exception as e:
            logger.error(
                f"❌ Ошибка записи дневного PnL: {e}",
                exc_info=True,
            )

    async def calculate_position_size(
        self,
        balance: Optional[
            float
        ] = None,  # ✅ НОВОЕ: Опциональный баланс (читаем из DataRegistry если не передан)
        price: float = 0.0,
        signal: Optional[Dict[str, Any]] = None,
        signal_generator=None,
    ) -> float:
        """
        Рассчитывает размер позиции с учетом Balance Profiles и режима рынка.
        ✅ РЕФАКТОРИНГ: Вся логика перенесена из orchestrator._calculate_position_size
        ✅ НОВОЕ: Баланс читается из DataRegistry, если не передан

        Args:
            balance: Текущий баланс (опционально, читается из DataRegistry если не передан)
            price: Текущая цена
            signal: Торговый сигнал
            signal_generator: Signal generator для определения режима

        Returns:
            float: Размер позиции в монетах (не USD!)
        """
        try:
            # ✅ КРИТИЧЕСКОЕ: Проверка max_daily_loss перед расчетом размера
            # Получаем баланс для проверки (если не передан, получим позже)
            check_balance = balance
            if check_balance is None and self.data_registry:
                try:
                    balance_data = await self.data_registry.get_balance()
                    if balance_data:
                        check_balance = balance_data.get("balance")
                except Exception:
                    pass

            if check_balance and check_balance > 0:
                if not await self._check_max_daily_loss(check_balance):
                    logger.warning(
                        f"⛔ Торговля остановлена из-за превышения max_daily_loss. "
                        f"Размер позиции не рассчитывается."
                    )
                    return 0.0

            # ✅ НОВОЕ: Получаем баланс из DataRegistry, если не передан
            if balance is None:
                if self.data_registry:
                    try:
                        balance_data = await self.data_registry.get_balance()
                        if balance_data:
                            balance = balance_data.get("balance")
                            logger.debug(
                                f"✅ RiskManager: Баланс получен из DataRegistry: ${balance:.2f}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Ошибка получения баланса из DataRegistry: {e}"
                        )

                # Fallback: если DataRegistry не доступен или нет данных
                if balance is None:
                    if self.client:
                        try:
                            balance = await self.client.get_balance()
                            logger.debug(
                                f"✅ RiskManager: Баланс получен из API: ${balance:.2f}"
                            )
                        except Exception as e:
                            logger.error(f"❌ Ошибка получения баланса из API: {e}")
                            return 0.0
                    else:
                        logger.error(
                            "❌ RiskManager: Нет доступа к балансу (нет data_registry и client)"
                        )
                        return 0.0

            if signal is None:
                signal = {}

            symbol = signal.get("symbol")
            symbol_regime = signal.get("regime")
            if (
                symbol
                and not symbol_regime
                and signal_generator
                and hasattr(signal_generator, "regime_managers")
            ):
                manager = signal_generator.regime_managers.get(symbol)
                if manager:
                    symbol_regime = manager.get_current_regime()
            if (
                not symbol_regime
                and signal_generator
                and hasattr(signal_generator, "regime_manager")
                and signal_generator.regime_manager
            ):
                symbol_regime = signal_generator.regime_manager.get_current_regime()

            balance_profile = self.config_manager.get_balance_profile(balance)

            # 🔥 АДАПТИВНЫЙ РАСЧЁТ (11.02.2026): маржа = balance × max_position_percent%
            # Истинная адаптивность — размер позиции всегда пропорционален текущему балансу.
            # Профиль (micro/small/medium/large) задаёт только процент и защитные лимиты.
            # При росте баланса 350$ → 1000$ → маржа автоматически растёт (% × баланс).
            is_progressive = (
                False  # Прогрессивная интерполяция заменена процентным расчётом
            )

            # Получаем leverage заранее (нужен для расчёта номинала)
            _leverage_for_size = None
            if signal:
                _leverage_for_size = signal.get("leverage")
            if not _leverage_for_size or _leverage_for_size <= 0:
                _leverage_for_size = getattr(self.scalping_config, "leverage", None)
            if not _leverage_for_size or _leverage_for_size <= 0:
                _leverage_for_size = 3  # fallback

            max_pct = balance_profile.get("max_position_percent", 15.0)
            margin_target_usd = balance * max_pct / 100.0  # целевая МАРЖА в USD
            base_usd_size = (
                margin_target_usd * _leverage_for_size
            )  # номинальная стоимость

            logger.info(
                f"📊 Адаптивный размер [{balance_profile.get('name', '?')}]: "
                f"${balance:.2f} × {max_pct}% = ${margin_target_usd:.2f} маржа "
                f"× {_leverage_for_size}x = ${base_usd_size:.2f} номинал"
            )

            min_usd_size = balance_profile["min_position_usd"]
            max_usd_size = balance_profile["max_position_usd"]

            # ✅ ВАРИАНТ B: Применить per-symbol множитель к базовому размеру
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
                            # 🔇 ИЗМЕНЕНО (2026-02-08): INFO → DEBUG для снижения объема логов
                            logger.debug(
                                f"📊 Per-symbol multiplier для {symbol}: {position_multiplier}x "
                                f"→ размер ${original_size:.2f} → ${base_usd_size:.2f}"
                            )
                        # else:
                        #     logger.debug(
                        #         f"📊 Per-symbol multiplier для {symbol}: {position_multiplier}x "
                        #         f"→ размер ${original_size:.2f} (без изменений)"
                        #     )
                    # else:
                    #     logger.debug(
                    #         f"📊 Per-symbol multiplier для {symbol}: не найден "
                    #         f"(используем базовый размер ${base_usd_size:.2f})"
                    #     )
                # else:
                #     logger.debug(
                #         f"⚠️ symbol_profile не найден для {symbol} в symbol_profiles"
                #     )

            # Применяем position overrides (если указаны, они имеют приоритет для точной настройки)
            position_overrides: Dict[str, Any] = {}
            if symbol:
                regime_profile = self._get_symbol_regime_profile(symbol, symbol_regime)
                position_overrides = self.config_manager.to_dict(
                    regime_profile.get("position", {})
                )

            # ⚠️ ВАЖНО: position overrides из symbol_profiles могут быть устаревшими
            # Они применяются только если явно указаны и имеют приоритет над multiplier
            # Для новой системы рекомендуется использовать только position_multiplier
            if position_overrides.get("base_position_usd") is not None:
                # ✅ ИСПРАВЛЕНО: Игнорируем override если он меньше базового размера
                override_size = float(position_overrides["base_position_usd"])
                if override_size < base_usd_size:
                    logger.debug(
                        f"⚠️ Игнорируем position override для {symbol}: "
                        f"${override_size:.2f} < базовый ${base_usd_size:.2f} (из balance_profile)"
                    )
                elif abs(override_size - base_usd_size) / base_usd_size > 0.5:
                    logger.debug(
                        f"⚠️ Игнорируем устаревший position override для {symbol}: "
                        f"${override_size:.2f} (используем multiplier: ${base_usd_size:.2f})"
                    )
                else:
                    base_usd_size = override_size
                    logger.info(
                        f"📊 Используем position override для {symbol}: ${base_usd_size:.2f} (увеличен с базового)"
                    )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: min/max из symbol_profiles не должны уменьшать значения из balance_profile
            if position_overrides.get("min_position_usd") is not None:
                symbol_min = float(position_overrides["min_position_usd"])
                balance_min = min_usd_size
                if symbol_min > min_usd_size:
                    min_usd_size = symbol_min
                    logger.debug(
                        f"📊 Min position size из symbol_profiles (${symbol_min:.2f}) больше "
                        f"balance_profile (${balance_min:.2f}), используем ${symbol_min:.2f}"
                    )
                else:
                    logger.debug(
                        f"📊 Min position size из symbol_profiles (${symbol_min:.2f}) меньше или равно "
                        f"balance_profile (${balance_min:.2f}), игнорируем (используем ${balance_min:.2f})"
                    )

            if position_overrides.get("max_position_usd") is not None:
                symbol_max = float(position_overrides["max_position_usd"])
                balance_max = max_usd_size

                # 🔴 BUG #28 FIX: используем min(per_symbol, global) и логируем конфликт
                if symbol_max < balance_max:
                    logger.info(
                        f"⚠️ max_position_usd per-symbol (${symbol_max:.2f}) < global (${balance_max:.2f}), используем min=${symbol_max:.2f}"
                    )
                    max_usd_size = symbol_max
                else:
                    max_usd_size = balance_max
                    logger.debug(
                        f"📊 max_position_usd per-symbol (${symbol_max:.2f}) >= global (${balance_max:.2f}), оставляем global ${balance_max:.2f}"
                    )

                if max_usd_size < min_usd_size:
                    logger.warning(
                        f"⚠️ Конфликт лимитов: max_position_usd (${max_usd_size:.2f}) < "
                        f"min_position_usd (${min_usd_size:.2f}) для {symbol}. "
                        f"Используем max_position_usd = min_position_usd (${min_usd_size:.2f})."
                    )
                    max_usd_size = min_usd_size

            if position_overrides.get("max_position_percent") is not None:
                max_pct = position_overrides["max_position_percent"]
                if max_pct is not None:
                    balance_profile["max_position_percent"] = float(max_pct)

            # ✅ МОДЕРНИЗАЦИЯ: Убираем fallback значения, требуем из конфига
            if min_usd_size is None or min_usd_size <= 0:
                logger.error(
                    f"❌ min_position_usd не указан в конфиге для профиля {balance_profile.get('name', 'unknown')}! "
                    f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {balance_profile.get('name', 'unknown')} -> min_position_usd"
                )
                raise ValueError(
                    f"min_position_usd должен быть указан в конфиге для профиля {balance_profile.get('name', 'unknown')}"
                )
            if max_usd_size is None or max_usd_size <= 0:
                logger.error(
                    f"❌ max_position_usd не указан в конфиге для профиля {balance_profile.get('name', 'unknown')}! "
                    f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {balance_profile.get('name', 'unknown')} -> max_position_usd"
                )
                raise ValueError(
                    f"max_position_usd должен быть указан в конфиге для профиля {balance_profile.get('name', 'unknown')}"
                )

            # ✅ МОДЕРНИЗАЦИЯ: Убираем fallback значения, требуем из конфига
            profile_max_positions = balance_profile.get("max_open_positions")
            if profile_max_positions is None or profile_max_positions <= 0:
                logger.error(
                    f"❌ max_open_positions не указан в конфиге для профиля {balance_profile.get('name', 'unknown')}! "
                    f"Проверьте config_futures.yaml -> scalping -> balance_profiles -> {balance_profile.get('name', 'unknown')} -> max_open_positions"
                )
                raise ValueError(
                    f"max_open_positions должен быть указан в конфиге для профиля {balance_profile.get('name', 'unknown')}"
                )

            if position_overrides.get("max_open_positions") is not None:
                profile_max_positions = int(position_overrides["max_open_positions"])
            global_max_positions = getattr(
                self.risk_config, "max_open_positions", profile_max_positions
            )
            if profile_max_positions:
                allowed_positions = max(
                    1, min(profile_max_positions, global_max_positions)
                )
                if (
                    self.max_size_limiter
                    and self.max_size_limiter.max_positions != allowed_positions
                ):
                    logger.debug(
                        f"🔧 MaxSizeLimiter: обновляем max_positions {self.max_size_limiter.max_positions} → {allowed_positions}"
                    )
                    self.max_size_limiter.max_positions = allowed_positions
                if self.max_size_limiter:
                    max_total_size = max_usd_size * allowed_positions
                    if self.max_size_limiter.max_total_size_usd != max_total_size:
                        logger.debug(
                            f"🔧 MaxSizeLimiter: обновляем max_total_size_usd {self.max_size_limiter.max_total_size_usd:.2f} → {max_total_size:.2f}"
                        )
                        self.max_size_limiter.max_total_size_usd = max_total_size
                    if self.max_size_limiter.max_single_size_usd != max_usd_size:
                        logger.debug(
                            f"🔧 MaxSizeLimiter: обновляем max_single_size_usd {self.max_size_limiter.max_single_size_usd:.2f} → {max_usd_size:.2f}"
                        )
                        self.max_size_limiter.max_single_size_usd = max_usd_size
            else:
                logger.error(
                    f"❌ max_open_positions не указан или равен 0 для профиля {balance_profile.get('name', 'unknown')}!"
                )
                raise ValueError(
                    f"max_open_positions должен быть указан и > 0 в конфиге для профиля {balance_profile.get('name', 'unknown')}"
                )

            if (
                signal_generator
                and hasattr(signal_generator, "regime_manager")
                and signal_generator.regime_manager
            ):
                try:
                    regime_key = (
                        symbol_regime
                        or signal_generator.regime_manager.get_current_regime()
                    )
                    if regime_key:
                        regime_params = self.config_manager.get_regime_params(
                            regime_key, symbol
                        )
                        multiplier = regime_params.get("position_size_multiplier")
                        if multiplier is not None:
                            base_usd_size *= multiplier
                            logger.debug(f"Режим {regime_key}: multiplier={multiplier}")
                except Exception as e:
                    logger.warning(f"Ошибка адаптации под режим: {e}")

            has_conflict = signal.get("has_conflict", False)
            signal_strength = signal.get("strength", 0.5)

            # ✅ МОДЕРНИЗАЦИЯ: Получаем адаптивные параметры риска с учетом режима и баланса
            adaptive_risk_params = self.config_manager.get_adaptive_risk_params(
                balance, symbol_regime, symbol, signal_generator=signal_generator
            )
            strength_multipliers = adaptive_risk_params.get("strength_multipliers", {})
            strength_thresholds = adaptive_risk_params.get("strength_thresholds", {})

            # ✅ МОДЕРНИЗАЦИЯ: Используем адаптивные strength_multipliers из конфига
            if has_conflict:
                strength_multiplier = strength_multipliers.get("conflict", 0.5)
                logger.debug(
                    f"⚡ Конфликт RSI/EMA: уменьшенный размер для быстрого скальпа "
                    f"(strength={signal_strength:.2f}, multiplier={strength_multiplier})"
                )
            elif signal_strength > strength_thresholds.get("very_strong", 0.8):
                strength_multiplier = strength_multipliers.get("very_strong", 1.5)
                logger.debug(
                    f"Очень сильный сигнал (strength={signal_strength:.2f}): multiplier={strength_multiplier}"
                )
            elif signal_strength > strength_thresholds.get("strong", 0.6):
                strength_multiplier = strength_multipliers.get("strong", 1.2)
                logger.debug(
                    f"Хороший сигнал (strength={signal_strength:.2f}): multiplier={strength_multiplier}"
                )
            elif signal_strength > strength_thresholds.get("medium", 0.4):
                strength_multiplier = strength_multipliers.get("medium", 1.0)
                logger.debug(
                    f"Средний сигнал (strength={signal_strength:.2f}): multiplier={strength_multiplier}"
                )
            else:
                strength_multiplier = strength_multipliers.get("weak", 0.8)
                logger.debug(
                    f"Слабый сигнал (strength={signal_strength:.2f}): multiplier={strength_multiplier}"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для прогрессивных профилей уменьшаем multiplier
            # чтобы не перезаписывать прогрессивный расчет (уже выполнен выше при расчете base_usd_size)
            original_multiplier = strength_multiplier
            if is_progressive:
                # Для прогрессивных профилей используем меньший multiplier (0.9 вместо 0.8)
                # чтобы прогрессивный расчет работал правильно, но множители все равно влияли
                progressive_multiplier = (
                    0.9  # 90% от обычного multiplier (увеличено с 0.8)
                )
                strength_multiplier = (
                    1.0 + (strength_multiplier - 1.0) * progressive_multiplier
                )
                logger.debug(
                    f"📊 Прогрессивный профиль: уменьшаем multiplier до {strength_multiplier:.2f} "
                    f"(было бы {original_multiplier:.2f} без прогрессивной адаптации)"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Применяем multiplier, но ограничиваем max_usd_size!
            base_usd_size *= strength_multiplier
            # ✅ ИСПРАВЛЕНО: Строгая проверка max_position_size с логированием до/после
            base_usd_size_before_cap = base_usd_size
            if base_usd_size > max_usd_size:
                base_usd_size = max_usd_size * 0.95  # ✅ ПРАВКА #7: 5% запас
                logger.warning(
                    f"⚠️ Размер позиции ${base_usd_size_before_cap:.2f} превышает max_position_size ${max_usd_size:.2f} для {symbol}! "
                    f"Ограничиваем до ${base_usd_size:.2f} (5% запас, сигнал был сильный: strength_multiplier={strength_multiplier:.2f}x)"
                )
            logger.info(
                f"💰 Position size: ${base_usd_size_before_cap:.2f} → ${base_usd_size:.2f} USD after cap "
                f"(max=${max_usd_size:.2f}, progressive={is_progressive}, multiplier={strength_multiplier:.2f})"
            )

            # ✅ ОПТИМИЗАЦИЯ #4: Динамический размер позиций на основе волатильности (ATR-based)
            volatility_adjustment_enabled = False
            volatility_multiplier = 1.0
            try:
                volatility_config = getattr(
                    self.scalping_config, "volatility_adjustment", None
                )
                if volatility_config is None:
                    volatility_config = {}
                elif not isinstance(volatility_config, dict):
                    volatility_config = self.config_manager.to_dict(volatility_config)

                volatility_adjustment_enabled = volatility_config.get("enabled", False)

                if volatility_adjustment_enabled and symbol and price > 0:
                    base_atr_percent = volatility_config.get("base_atr_percent", 0.02)
                    min_multiplier = volatility_config.get("min_multiplier", 0.5)
                    max_multiplier = volatility_config.get("max_multiplier", 1.5)

                    regime_configs = volatility_config.get("by_regime", {})
                    if symbol_regime and symbol_regime.lower() in regime_configs:
                        regime_config = regime_configs[symbol_regime.lower()]
                        base_atr_percent = regime_config.get(
                            "base_atr_percent", base_atr_percent
                        )
                        min_multiplier = regime_config.get(
                            "min_multiplier", min_multiplier
                        )
                        max_multiplier = regime_config.get(
                            "max_multiplier", max_multiplier
                        )

                    # Получаем ATR через signal_generator
                    current_atr_percent = None
                    try:
                        if signal_generator and hasattr(
                            signal_generator, "_get_market_data"
                        ):
                            market_data = await signal_generator._get_market_data(
                                symbol
                            )
                            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (27.12.2025): Используем адаптивный ATR период
                            atr_period = 14  # Fallback
                            if signal_generator and hasattr(
                                signal_generator, "_get_regime_indicators_params"
                            ):
                                try:
                                    regime_params = (
                                        signal_generator._get_regime_indicators_params(
                                            symbol=symbol
                                        )
                                    )
                                    atr_period = regime_params.get("atr_period", 14)
                                except Exception:
                                    pass

                            if (
                                market_data
                                and market_data.ohlcv_data
                                and len(market_data.ohlcv_data) >= atr_period + 1
                            ):
                                from src.indicators import ATR

                                atr_indicator = ATR(period=atr_period)
                                high_data = [
                                    candle.high for candle in market_data.ohlcv_data
                                ]
                                low_data = [
                                    candle.low for candle in market_data.ohlcv_data
                                ]
                                close_data = [
                                    candle.close for candle in market_data.ohlcv_data
                                ]

                                atr_result = atr_indicator.calculate(
                                    high_data, low_data, close_data
                                )
                                if atr_result and atr_result.value > 0:
                                    atr_value = atr_result.value
                                    current_atr_percent = (
                                        atr_value / price
                                    ) * 100  # ATR в % от цены
                    except Exception as e:
                        logger.debug(f"⚠️ Не удалось получить ATR для {symbol}: {e}")

                    # Рассчитываем multiplier на основе волатильности
                    if current_atr_percent is not None and current_atr_percent > 0:
                        raw_multiplier = base_atr_percent / (
                            current_atr_percent / 100.0
                        )
                        # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Приводим к float, чтобы избежать умножения строки
                        volatility_multiplier = float(
                            max(min_multiplier, min(raw_multiplier, max_multiplier))
                        )

                        logger.info(
                            f"  4a. Волатильность (ATR): текущая={current_atr_percent:.4f}%, "
                            f"базовая={base_atr_percent*100:.2f}%, multiplier={volatility_multiplier:.2f}x"
                        )

                        base_usd_size_before_vol = base_usd_size
                        base_usd_size *= volatility_multiplier
                        # ✅ ИСПРАВЛЕНО: Строгая проверка max_position_size после волатильности с логированием
                        base_usd_size_before_vol_cap = base_usd_size
                        if base_usd_size > max_usd_size:
                            logger.warning(
                                f"⚠️ Размер позиции после волатильности ${base_usd_size:.2f} "
                                f"превышает max_position_size ${max_usd_size:.2f} для {symbol}! "
                                f"Ограничиваем до ${max_usd_size:.2f} "
                                f"(volatility_multiplier={volatility_multiplier:.2f}x, strength_multiplier={strength_multiplier:.2f}x)"
                            )
                            base_usd_size = max_usd_size
                        if base_usd_size_before_vol_cap != base_usd_size:
                            logger.info(
                                f"💰 Position size after volatility: ${base_usd_size_before_vol_cap:.2f} → ${base_usd_size:.2f} USD after cap"
                            )

                        if abs(volatility_multiplier - 1.0) > 0.01:
                            logger.info(
                                f"  4b. Размер скорректирован волатильностью: "
                                f"${base_usd_size_before_vol:.2f} → ${base_usd_size:.2f} "
                                f"({volatility_multiplier:.2f}x)"
                            )
                    else:
                        logger.debug(
                            f"  4a. Волатильность: ATR не доступен для {symbol}, используем базовый размер"
                        )
            except Exception as e:
                logger.debug(f"⚠️ Ошибка расчета волатильности для {symbol}: {e}")

            # 4. ПРИМЕНЯЕМ ЛЕВЕРИДЖ (Futures) - из signal или из конфига!
            # ✅ ИСПРАВЛЕНИЕ: Сначала пытаемся получить leverage из signal (адаптивный)
            leverage = None
            if signal:
                leverage = signal.get("leverage")
                if leverage and leverage > 0:
                    logger.debug(
                        f"✅ Используем leverage={leverage}x из signal (адаптивный)"
                    )

            # Fallback на конфиг, если не был указан в signal
            if leverage is None or leverage <= 0:
                leverage = getattr(self.scalping_config, "leverage", None)
                if leverage and leverage > 0:
                    logger.debug(
                        f"✅ Используем leverage={leverage}x из конфига (фиксированный)"
                    )

            if leverage is None or leverage <= 0:
                logger.error(
                    "❌ leverage не указан в signal и не указан в конфиге или <= 0! Проверьте config_futures.yaml"
                )
                raise ValueError(
                    "leverage должен быть указан в signal или в конфиге (например, leverage: 3)"
                )
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: base_usd_size это НОМИНАЛЬНАЯ стоимость (notional)
            margin_required_initial = (
                base_usd_size / leverage
            )  # Требуемая маржа (в USD)
            margin_required = margin_required_initial

            # ✅ Пересчитываем min/max из номинальной стоимости в маржу для проверок
            min_margin_usd = min_usd_size / leverage
            max_margin_usd = max_usd_size / leverage

            # ✅ МОДЕРНИЗАЦИЯ: Получаем использованную маржу с биржи (актуальные данные)
            used_margin = await self._get_used_margin()
            # Обновляем total_margin_used через orchestrator
            if self.orchestrator and hasattr(self.orchestrator, "total_margin_used"):
                self.orchestrator.total_margin_used = used_margin

            # ✅ МОДЕРНИЗАЦИЯ: Получаем адаптивные параметры риска с учетом режима и баланса
            adaptive_risk_params = self.config_manager.get_adaptive_risk_params(
                balance, symbol_regime, symbol, signal_generator=signal_generator
            )
            max_margin_percent = (
                adaptive_risk_params.get("max_margin_percent", 80.0) / 100.0
            )
            max_loss_per_trade_percent = (
                adaptive_risk_params.get("max_loss_per_trade_percent", 2.0) / 100.0
            )
            max_margin_safety_percent = (
                adaptive_risk_params.get("max_margin_safety_percent", 90.0) / 100.0
            )

            # ✅ КРИТИЧЕСКОЕ УЛУЧШЕНИЕ (04.01.2026): Детальное логирование расчета margin для каждой пары
            logger.info(
                f"📊 [PARAMS_MARGIN] {symbol} ({symbol_regime or 'unknown'}): ДЕТАЛЬНЫЙ РАСЧЕТ МАРЖИ:"
            )
            logger.info(
                f"  1. Балансовый профиль: {balance_profile['name']}, баланс=${balance:.2f}"
            )
            logger.info(
                f"  2. Базовый размер из конфига: base_usd_size=${base_usd_size:.2f} (notional)"
            )
            logger.info(
                f"  3. Лимиты из конфига: min=${min_usd_size:.2f}, max=${max_usd_size:.2f} (notional)"
            )
            logger.info(
                f"  4. Леверидж: {leverage}x → маржа до ограничений: ${margin_required_initial:.2f} "
                f"(расчет: ${base_usd_size:.2f} / {leverage}x = ${margin_required_initial:.2f})"
            )
            logger.info(
                f"  5. Использованная маржа: ${used_margin:.2f}, доступная: ${balance - used_margin:.2f}"
            )

            # ✅ МОДЕРНИЗАЦИЯ: Используем использованную маржу с биржи (актуальные данные)
            # 5. 🛡️ ЗАЩИТА: Max Margin Used (адаптивный процент из конфига)
            max_margin_allowed = balance * max_margin_percent
            available_margin = balance - used_margin

            logger.info(
                f"  6. Max margin percent: {max_margin_percent*100:.1f}% → лимит: ${max_margin_allowed:.2f}"
            )
            if used_margin + margin_required > max_margin_allowed:
                margin_required_before = margin_required
                margin_required = max(0, max_margin_allowed - used_margin)
                logger.warning(
                    f"     ⚠️ ОГРАНИЧЕНО: max_margin_allowed (${max_margin_allowed:.2f}) → margin: ${margin_required_before:.2f} → ${margin_required:.2f} (уменьшено на ${margin_required_before - margin_required:.2f} или {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                )
                if margin_required < min_margin_usd:
                    logger.error(
                        f"❌ Недостаточно свободной маржи для открытия позиции "
                        f"(использовано: ${used_margin:.2f}, доступно: ${available_margin:.2f}, "
                        f"требуется минимум: ${min_margin_usd:.2f} маржи)"
                    )
                    return 0.0

            # ✅ МОДЕРНИЗАЦИЯ: Дополнительная проверка на доступную маржу
            logger.info(f"  7. Доступная маржа: ${available_margin:.2f}")
            if margin_required > available_margin:
                margin_required_before = margin_required
                margin_required = max(0, available_margin)
                logger.warning(
                    f"     ⚠️ ОГРАНИЧЕНО: available_margin (${available_margin:.2f}) → margin: ${margin_required_before:.2f} → ${margin_required:.2f} (уменьшено на ${margin_required_before - margin_required:.2f} или {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                )
                if margin_required < min_margin_usd:
                    logger.error(
                        f"❌ Недостаточно доступной маржи для открытия позиции "
                        f"(доступно: ${available_margin:.2f}, требуется минимум: ${min_margin_usd:.2f} маржи)"
                    )
                    return 0.0

            # ✅ НОВОЕ: Динамический кап маржи (Уровень 2: margin-per-trade)
            dynamic_margin_cap = None
            try:
                risk_config = getattr(self.scalping_config, "risk_config", {})
                if isinstance(risk_config, dict):
                    use_dynamic_cap = (
                        risk_config.get("max_margin_per_trade") is not None
                    )
                else:
                    use_dynamic_cap = hasattr(risk_config, "max_margin_per_trade")

                if use_dynamic_cap:
                    # Получаем волатильность для расчета
                    volatility_atr = None
                    try:
                        if signal_generator and hasattr(
                            signal_generator, "data_registry"
                        ):
                            data_registry = signal_generator.data_registry
                            if data_registry:
                                atr_data = await data_registry.get_indicator(
                                    symbol, "atr"
                                )  # ✅ ИСПРАВЛЕНО: добавлен await
                                if atr_data and price > 0:
                                    volatility_atr = (
                                        float(atr_data) / price
                                    )  # ATR % от цены
                    except Exception as e:
                        logger.debug(
                            f"⚠️ Не удалось получить волатильность для dynamic_cap: {e}"
                        )

                    # Получаем дневной PnL
                    daily_pnl = getattr(self, "daily_pnl", 0.0)

                    # Рассчитываем динамический кап
                    dynamic_margin_cap = self._calculate_dynamic_margin_cap(
                        balance=balance,
                        symbol=symbol,
                        regime=symbol_regime or "trending",
                        volatility=volatility_atr,
                        daily_pnl=daily_pnl,
                        open_positions_margin=used_margin,
                    )

                    volatility_str = (
                        f"{volatility_atr*100:.2f}%"
                        if volatility_atr is not None
                        else "N/A"
                    )
                    logger.info(
                        f"  8a. Dynamic margin cap: ${dynamic_margin_cap:.2f} "
                        f"(volatility={volatility_str}, daily_pnl=${daily_pnl:.2f})"
                    )

                    if margin_required > dynamic_margin_cap:
                        margin_required_before = margin_required
                        margin_required = dynamic_margin_cap
                        logger.warning(
                            f"     ⚠️ ОГРАНИЧЕНО: dynamic_margin_cap (${dynamic_margin_cap:.2f}) → margin: ${margin_required_before:.2f} → ${margin_required:.2f} "
                            f"(уменьшено на ${margin_required_before - margin_required:.2f} или {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                        )
            except Exception as e:
                logger.debug(f"⚠️ Ошибка расчета dynamic_margin_cap: {e}")

            # ✅ НОВОЕ: Risk-based margin (Уровень 3: Margin Budget)
            risk_based_margin = None
            try:
                risk_config = getattr(self.scalping_config, "risk_config", {})
                if isinstance(risk_config, dict):
                    use_risk_based = risk_config.get("use_risk_based_sizing", False)
                else:
                    use_risk_based = getattr(
                        risk_config, "use_risk_based_sizing", False
                    )

                if use_risk_based and price > 0:
                    # Получаем risk_per_trade из конфига
                    risk_per_trade = (
                        max_loss_per_trade_percent  # Используем тот же параметр
                    )

                    # Получаем sl_percent
                    sl_percent = self._resolve_sl_percent_for_risk(
                        symbol, symbol_regime
                    )
                    # ✅ ЕДИНЫЙ СТАНДАРТ: sl_percent в конфиге = процентные пункты (0.8 = 0.8%)
                    # В risk-based формуле нужен SL в доле (0.008 = 0.8%)
                    sl_percent_decimal = pct_points_to_fraction(sl_percent)

                    # Рассчитываем risk-based margin
                    risk_based_margin = self._calculate_risk_based_margin(
                        balance=balance,
                        risk_per_trade=risk_per_trade,
                        sl_distance_pct=sl_percent_decimal,
                        leverage=leverage,
                        price=price,
                    )

                    logger.info(
                        f"  8b. Risk-based margin: ${risk_based_margin:.2f} "
                        f"(risk={risk_per_trade*100:.2f}%, sl={sl_percent_decimal*100:.2f}%)"
                    )

                    if risk_based_margin > 0 and margin_required > risk_based_margin:
                        margin_required_before = margin_required
                        margin_required = risk_based_margin
                        logger.warning(
                            f"     ⚠️ ОГРАНИЧЕНО: risk_based_margin (${risk_based_margin:.2f}) → margin: ${margin_required_before:.2f} → ${margin_required:.2f} "
                            f"(уменьшено на ${margin_required_before - margin_required:.2f} или {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                        )
            except Exception as e:
                logger.debug(f"⚠️ Ошибка расчета risk_based_margin: {e}")

            # 6. 🛡️ ЗАЩИТА: Max Loss per Trade (адаптивный процент из конфига)
            max_loss_usd = balance * max_loss_per_trade_percent
            sl_percent = self._resolve_sl_percent_for_risk(symbol, symbol_regime)

            # ✅ ЕДИНЫЙ СТАНДАРТ: sl_percent в конфиге = процентные пункты (0.8 = 0.8%)
            sl_percent_decimal = pct_points_to_fraction(sl_percent)

            max_safe_margin = (
                max_loss_usd / sl_percent_decimal
                if sl_percent_decimal > 0
                else float("inf")
            )

            logger.info(
                f"  8. Max loss per trade: {max_loss_per_trade_percent*100:.1f}% (${max_loss_usd:.2f}) → max_safe_margin: ${max_safe_margin:.2f}"
            )
            if margin_required > max_safe_margin:
                margin_required_before = margin_required
                margin_required = max_safe_margin
                logger.warning(
                    f"     ⚠️ ОГРАНИЧЕНО: max_safe_margin (${max_safe_margin:.2f}) → margin: ${margin_required_before:.2f} → ${margin_required:.2f} (уменьшено на ${margin_required_before - margin_required:.2f} или {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                )

            # 7. Проверка маржи (адаптивный процент безопасности из конфига - финальная проверка)
            max_margin_safety = balance * max_margin_safety_percent
            logger.info(
                f"  9. Max margin safety: {max_margin_safety_percent*100:.1f}% → лимит: ${max_margin_safety:.2f}"
            )
            if margin_required > max_margin_safety:
                margin_required_before = margin_required
                margin_required = max_margin_safety
                logger.warning(
                    f"     ⚠️ ОГРАНИЧЕНО: max_margin_safety (${max_margin_safety:.2f}) → margin: ${margin_required_before:.2f} → ${margin_required:.2f} (уменьшено на ${margin_required_before - margin_required:.2f} или {((margin_required_before - margin_required) / margin_required_before * 100) if margin_required_before > 0 else 0:.1f}%)"
                )

            # 8. ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Применяем ограничения к МАРЖЕ (не к notional!)
            margin_before_final = margin_required
            logger.info(
                f"  10. Финальные лимиты: min_margin=${min_margin_usd:.2f}, max_margin=${max_margin_usd:.2f}"
            )
            margin_usd = max(min_margin_usd, min(margin_required, max_margin_usd))

            logger.info(
                f"  11. ИТОГО: margin=${margin_usd:.2f} (начальная: ${margin_required_initial:.2f}, после ограничений: ${margin_before_final:.2f})"
            )
            if margin_usd < margin_required_initial:
                reduction_pct = (
                    (
                        (margin_required_initial - margin_usd)
                        / margin_required_initial
                        * 100
                    )
                    if margin_required_initial > 0
                    else 0
                )
                logger.warning(
                    f"     ⚠️ РАЗМЕР УМЕНЬШЕН: ${margin_required_initial:.2f} → ${margin_usd:.2f} (на ${margin_required_initial - margin_usd:.2f} или {reduction_pct:.1f}%)"
                )

            # 9. ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Переводим МАРЖУ в количество монет
            position_size = (margin_usd * leverage) / price

            # ✅ НОВОЕ: Учитываем округление при конвертации в контракты
            ct_val = None
            lot_sz = None
            min_sz = None

            try:
                instrument_details = await self.client.get_instrument_details(symbol)
                ct_val = instrument_details.get("ctVal", 0.01)
                lot_sz = instrument_details.get("lotSz", 0.01)
                min_sz = instrument_details.get("minSz", 0.01)

                from src.clients.futures_client import round_to_step

                size_in_contracts = position_size / ct_val
                rounded_size_in_contracts = round_to_step(size_in_contracts, lot_sz)

                if rounded_size_in_contracts < min_sz:
                    rounded_size_in_contracts = min_sz
                    logger.warning(
                        f"⚠️ Размер после округления меньше минимума, используем минимум: {min_sz}"
                    )

                real_position_size = rounded_size_in_contracts * ct_val
                real_notional_usd = real_position_size * price
                real_margin_usd = real_notional_usd / leverage

                # ✅ КРИТИЧЕСКАЯ ПРОВЕРКА: Проверяем, что реальный размер после округления >= min_margin_usd
                if real_margin_usd < min_margin_usd:
                    logger.warning(
                        f"⚠️ Реальный размер после округления слишком маленький: "
                        f"margin=${real_margin_usd:.2f} < min=${min_margin_usd:.2f}, "
                        f"увеличиваем до минимума"
                    )
                    real_margin_usd = min_margin_usd
                    real_notional_usd = real_margin_usd * leverage
                    real_position_size = real_notional_usd / price

                    real_size_in_contracts = real_position_size / ct_val
                    real_rounded_size_in_contracts = round_to_step(
                        real_size_in_contracts, lot_sz
                    )
                    if real_rounded_size_in_contracts < min_sz:
                        real_rounded_size_in_contracts = min_sz
                    real_position_size = real_rounded_size_in_contracts * ct_val
                    real_notional_usd = real_position_size * price
                    real_margin_usd = real_notional_usd / leverage

                    logger.info(
                        f"✅ Размер позиции увеличен до минимума: "
                        f"margin=${real_margin_usd:.2f}, "
                        f"notional=${real_notional_usd:.2f}, "
                        f"position_size={real_position_size:.6f} монет"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем лимиты ПОСЛЕ округления
                if real_notional_usd > max_usd_size:
                    logger.warning(
                        f"⚠️ Реальный размер после округления превышает лимит: "
                        f"notional=${real_notional_usd:.2f} > max=${max_usd_size:.2f}, "
                        f"уменьшаем до лимита с учетом округления"
                    )
                    import math

                    target_notional_usd = max_usd_size
                    target_margin_usd = target_notional_usd / leverage
                    target_position_size = target_notional_usd / price
                    target_size_in_contracts = target_position_size / ct_val
                    target_rounded_size_in_contracts = (
                        math.floor(target_size_in_contracts / lot_sz) * lot_sz
                    )

                    if target_rounded_size_in_contracts < min_sz:
                        min_notional_usd = min_sz * ct_val * price
                        if min_notional_usd > max_usd_size:
                            logger.error(
                                f"❌ КРИТИЧЕСКАЯ ОШИБКА: Минимальный размер позиции ({min_notional_usd:.2f} USD) превышает лимит ({max_usd_size:.2f} USD)! "
                                f"Невозможно открыть позицию для {symbol}. "
                                f"Проверьте конфигурацию: min_position_usd и max_position_usd в config_futures.yaml"
                            )
                            return 0.0
                        else:
                            target_rounded_size_in_contracts = min_sz

                    real_position_size = target_rounded_size_in_contracts * ct_val
                    real_notional_usd = real_position_size * price
                    real_margin_usd = real_notional_usd / leverage

                    if real_notional_usd > max_usd_size:
                        logger.error(
                            f"❌ КРИТИЧЕСКАЯ ОШИБКА: Минимальный размер позиции ({real_notional_usd:.2f} USD) превышает лимит ({max_usd_size:.2f} USD)! "
                            f"Невозможно открыть позицию для {symbol}. "
                            f"Проверьте конфигурацию: min_position_usd и max_position_usd в config_futures.yaml"
                        )
                        return 0.0

                    logger.info(
                        f"✅ Размер позиции уменьшен до лимита: "
                        f"margin=${real_margin_usd:.2f}, "
                        f"notional=${real_notional_usd:.2f}, "
                        f"position_size={real_position_size:.6f} монет"
                    )

                # Логируем округление
                if abs(real_position_size - position_size) > 1e-8:
                    reduction_pct = (
                        ((position_size - real_position_size) / position_size * 100)
                        if position_size > 0
                        else 0
                    )
                    logger.warning(
                        f"⚠️ Размер позиции изменен из-за округления/минимума: "
                        f"{position_size:.6f} → {real_position_size:.6f} монет "
                        f"({reduction_pct:+.2f}%), "
                        f"notional: ${margin_usd * leverage:.2f} → ${real_notional_usd:.2f}, "
                        f"margin: ${margin_usd:.2f} → ${real_margin_usd:.2f}"
                    )
                else:
                    logger.info(
                        f"✅ Размер позиции после округления не изменился: "
                        f"{position_size:.6f} монет, "
                        f"notional=${real_notional_usd:.2f}, "
                        f"margin=${real_margin_usd:.2f}"
                    )

                position_size = real_position_size
                notional_usd = real_notional_usd
                margin_usd = real_margin_usd

            except Exception as e:
                logger.warning(
                    f"⚠️ Не удалось учесть округление при расчете размера позиции для {symbol}: {e}, "
                    f"используем расчетный размер без округления"
                )
                notional_usd = margin_usd * leverage

                if notional_usd > max_usd_size:
                    logger.warning(
                        f"⚠️ Итоговый размер позиции превышает лимит: "
                        f"notional=${notional_usd:.2f} > max=${max_usd_size:.2f}, "
                        f"уменьшаем размер позиции"
                    )
                    notional_usd = max_usd_size
                    margin_usd = notional_usd / leverage
                    position_size = notional_usd / price
                    logger.info(
                        f"✅ Размер позиции уменьшен до лимита: "
                        f"notional=${notional_usd:.2f}, margin=${margin_usd:.2f}, "
                        f"position_size={position_size:.6f} монет"
                    )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Финальная проверка лимитов ПОСЛЕ всех округлений
            if notional_usd > max_usd_size:
                logger.warning(
                    f"⚠️ Итоговый размер позиции превышает лимит: "
                    f"notional=${notional_usd:.2f} > max=${max_usd_size:.2f}, "
                    f"уменьшаем размер позиции"
                )
                notional_usd = max_usd_size
                margin_usd = notional_usd / leverage
                position_size = notional_usd / price
                logger.info(
                    f"✅ Размер позиции уменьшен до лимита: "
                    f"notional=${notional_usd:.2f}, margin=${margin_usd:.2f}, "
                    f"position_size={position_size:.6f} монет"
                )

            # 10. 🛡️ ЗАЩИТА: Проверяем drawdown перед открытием
            if not await self._check_drawdown_protection():
                logger.warning(
                    "⚠️ Drawdown protection активирован - пропускаем позицию"
                )
                return 0.0

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #3: Проверяем emergency stop перед открытием
            if (
                self.orchestrator
                and hasattr(self.orchestrator, "_emergency_stop_active")
                and self.orchestrator._emergency_stop_active
            ):
                await self._check_emergency_stop_unlock()
                if self.orchestrator._emergency_stop_active:
                    logger.warning(
                        "⚠️ Emergency stop активен - пропускаем позицию (торговля заблокирована)"
                    )
                    return 0.0

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ #5: Проверка минимального размера перед возвратом
            if symbol and price > 0:
                try:
                    # Получаем детали инструмента для проверки минимального размера
                    inst_details = await self.client.get_instrument_details(symbol)
                    ct_val = float(inst_details.get("ctVal") or 0.01)
                    min_sz = float(inst_details.get("minSz") or 0.01)

                    # Конвертируем размер из монет в контракты
                    size_in_contracts = position_size / ct_val if ct_val > 0 else 0

                    if size_in_contracts < min_sz:
                        # Размер меньше минимума - увеличиваем до минимума
                        min_size_in_coins = min_sz * ct_val
                        logger.warning(
                            f"⚠️ Рассчитанный размер позиции {symbol} меньше минимума биржи: "
                            f"{size_in_contracts:.6f} контрактов < {min_sz:.6f} контрактов. "
                            f"Увеличиваем до минимума: {position_size:.6f} → {min_size_in_coins:.6f} монет"
                        )
                        position_size = min_size_in_coins

                        # Пересчитываем notional и margin для нового размера
                        notional_usd = position_size * price
                        margin_usd = (
                            notional_usd / leverage if leverage > 0 else notional_usd
                        )

                        logger.info(
                            f"💰 РАСЧЕТ СКОРРЕКТИРОВАН: position_size={position_size:.6f} монет "
                            f"({min_sz:.6f} контрактов), notional=${notional_usd:.2f}, margin=${margin_usd:.2f}"
                        )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Не удалось проверить минимальный размер для {symbol}: {e}, "
                        f"используем рассчитанный размер {position_size:.6f} монет"
                    )

            # ✅ НОВОЕ (26.12.2025): Детальное логирование итогового расчета размера позиции
            logger.info("=" * 80)
            logger.info(f"💰 ФИНАЛЬНЫЙ РАСЧЕТ РАЗМЕРА ПОЗИЦИИ для {symbol}:")
            logger.info(
                f"   Баланс: ${balance:.2f} (профиль: {balance_profile['name']})"
            )
            logger.info(f"   Базовый размер (notional): ${base_usd_size:.2f}")
            if is_progressive:
                logger.info(
                    f"   Прогрессивный расчет: ${size_at_min:.2f} → ${size_at_max:.2f}"  # noqa: F821
                )

            # Получаем все множители для логирования
            position_multiplier_used = None
            if symbol:
                symbol_profile = self.symbol_profiles.get(symbol, {})
                if symbol_profile:
                    symbol_dict = (
                        self.config_manager.to_dict(symbol_profile)
                        if not isinstance(symbol_profile, dict)
                        else symbol_profile
                    )
                    position_multiplier_used = symbol_dict.get("position_multiplier")

            if position_multiplier_used and position_multiplier_used != 1.0:
                logger.info(f"   Per-symbol multiplier: {position_multiplier_used}x")

            if strength_multiplier != 1.0:
                logger.info(
                    f"   Strength multiplier: {strength_multiplier:.2f}x (сила сигнала: {signal_strength:.2f})"
                )

            if volatility_multiplier != 1.0:
                logger.info(f"   Volatility multiplier: {volatility_multiplier:.2f}x")

            # Получаем regime multiplier
            regime_multiplier_used = None
            if symbol_regime:
                regime_params = self.config_manager.get_regime_params(
                    symbol_regime, symbol
                )
                regime_multiplier_used = regime_params.get("position_size_multiplier")
                if regime_multiplier_used and regime_multiplier_used != 1.0:
                    logger.info(
                        f"   Regime multiplier ({symbol_regime}): {regime_multiplier_used:.2f}x"
                    )

            logger.info(f"   Леверидж: {leverage}x")
            logger.info(
                f"   Маржа: ${margin_usd:.2f} (лимит: ${min_margin_usd:.2f}-${max_margin_usd:.2f})"
            )
            logger.info(f"   Notional: ${notional_usd:.2f}")
            logger.info(
                f"   ИТОГОВЫЙ размер позиции: {position_size:.6f} монет (${notional_usd:.2f} notional, ${margin_usd:.2f} margin)"
            )
            logger.info("=" * 80)

            return position_size

        except Exception as e:
            logger.error(f"Ошибка расчета размера позиции: {e}", exc_info=True)
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
            # ✅ ИСПРАВЛЕНО (28.12.2025): Передаем orchestrator и data_registry для доступа к балансу
            return await self.margin_monitor.check_safety(
                position_size_usd,
                current_positions,
                orchestrator=self.orchestrator,  # ✅ Передаем orchestrator
                data_registry=self.data_registry,  # ✅ Передаем data_registry
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
            # 🔴 BUG #21 FIX: Получаем РЕАЛЬНУЮ маржу от API, не position_size
            current_price = entry_price  # Fallback: используем entry_price если не можем получить текущую
            margin = None

            # Пытаемся получить текущую цену
            try:
                if self.data_registry:
                    ticker_data = await self.data_registry.get_ticker(symbol)
                    if ticker_data and "last" in ticker_data:
                        raw_last = ticker_data.get("last")
                        if raw_last is not None:
                            current_price = float(raw_last)
            except Exception:
                pass

            # 🔴 BUG #21 FIX: Получаем маржу из позиции через API
            try:
                if self.client:
                    # Получаем информацию о позиции из OKX API
                    positions_data = await self.client.get_positions()
                    if positions_data:
                        for pos in positions_data:
                            if pos.get("instId") == f"{symbol}-SWAP":
                                # margin field содержит РЕАЛЬНУЮ маржу, не нотионал
                                margin = float(pos.get("margin", 0))
                                logger.debug(
                                    f"✓ Получена маржа для {symbol}: {margin} USDT"
                                )
                                break
            except Exception as e:
                logger.warning(f"⚠️ Не удалось получить маржу из API: {e}")

            # Fallback: если маржа не получена
            if margin is None or margin == 0:
                # Оцениваем маржу как position_size / leverage
                estimated_leverage = (
                    self.config.risk.leverage
                    if hasattr(self.config.risk, "leverage")
                    else 10
                )
                margin = position_size_usd / estimated_leverage
                logger.warning(
                    f"⚠️ Маржа не получена от API, используем оценку: {margin} USDT "
                    f"(position_size={position_size_usd}, leverage={estimated_leverage})"
                )

            # ✅ Формируем позицию как dict для LiquidationProtector
            position = {
                "side": side,
                "size": position_size_usd,
                "entry_price": entry_price,
                "avgPx": entry_price,
                "mark_price": current_price,
                "margin": margin,
            }
            # Вызываем check_liquidation_risk с правильными аргументами
            return await self.liquidation_protector.check_liquidation_risk(
                symbol=symbol,
                position=position,
                balance=margin,
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
