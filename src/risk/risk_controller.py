"""
Контроллер рисков.

Ответственность:
- Проверка лимитов позиций
- Проверка daily loss/profit limits
- Consecutive losses tracking
- Extended cooldown
- Emergency stop conditions
"""

import asyncio
from datetime import datetime
from typing import Dict, Tuple

from loguru import logger

from src.models import Position


class RiskController:
    """
    Контроллер рисков.

    Проверяет все риск-лимиты перед открытием позиций.
    """

    def __init__(
        self, config, risk_config, adaptive_regime=None, telegram_notifier=None
    ):
        """
        Args:
            config: Scalping конфигурация
            risk_config: Risk конфигурация
            adaptive_regime: ARM модуль (опционально)
            telegram_notifier: Telegram notifier (опционально)
        """
        self.config = config
        self.risk_config = risk_config
        self.adaptive_regime = adaptive_regime
        self.telegram = telegram_notifier

        # Лимиты
        self.max_consecutive_losses = 10  # 🔥 ИСПРАВЛЕНО: 3→10 (для скальпинга!)
        self.max_daily_loss_percent = risk_config.max_daily_loss_percent
        self.daily_profit_target_percent = 5.0  # Фиксация прибыли
        self.max_open_positions = risk_config.max_open_positions

        # Состояние
        self.consecutive_losses = 0
        self.last_trade_time = {}
        self.trade_count_hourly = 0
        self.hourly_reset_time = datetime.utcnow()

        logger.info(
            f"✅ RiskController initialized | "
            f"Max consecutive losses: {self.max_consecutive_losses} | "
            f"Max daily loss: {self.max_daily_loss_percent}% | "
            f"Telegram: {'ON' if self.telegram and self.telegram.enabled else 'OFF'}"
        )

    def can_trade(
        self, symbol: str, current_positions: Dict[str, Position], stats: Dict
    ) -> Tuple[bool, str]:
        """
        Проверка можно ли открывать новую позицию.

        Проверяет:
        1. Max открытых позиций
        2. Daily loss limit
        3. Daily profit target (lock profits)
        4. Consecutive losses
        5. Extended cooldown
        6. Hourly trade limit (ARM)
        7. Cooldown после последней сделки

        Args:
            symbol: Торговый символ
            current_positions: Текущие открытые позиции
            stats: Статистика торговли

        Returns:
            (bool: разрешено, str: причина)
        """

        # 1. Max открытых позиций
        if len(current_positions) >= self.max_open_positions:
            return False, f"Max open positions ({self.max_open_positions})"

        # 2. Daily loss limit
        daily_pnl = stats.get("daily_pnl", 0.0)
        start_balance = stats.get("start_balance", 1000.0)

        if start_balance > 0:
            daily_loss_percent = (daily_pnl / start_balance) * 100

            if daily_loss_percent <= -self.max_daily_loss_percent:
                return (
                    False,
                    f"Daily loss limit ({daily_loss_percent:.2f}% <= -{self.max_daily_loss_percent}%)",
                )

        # 3. Daily profit target (фиксация прибыли)
        if start_balance > 0:
            daily_profit_percent = (daily_pnl / start_balance) * 100

            if daily_profit_percent >= self.daily_profit_target_percent:
                return (
                    False,
                    f"Daily profit target reached ({daily_profit_percent:.2f}% >= {self.daily_profit_target_percent}%)",
                )

        # 4. Consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            return (
                False,
                f"Max consecutive losses ({self.consecutive_losses}/{self.max_consecutive_losses})",
            )

        # 5. Extended cooldown (после 2+ убытков)
        if self.consecutive_losses >= 2:
            extended_cooldown_minutes = 15
            last_trade = self.last_trade_time.get(symbol)

            if last_trade:
                time_since_last = (datetime.utcnow() - last_trade).total_seconds() / 60

                if time_since_last < extended_cooldown_minutes:
                    remaining = extended_cooldown_minutes - time_since_last
                    return (
                        False,
                        f"Extended cooldown active ({remaining:.1f} min remaining)",
                    )

        # 6. Hourly trade limit (ARM)
        max_trades_per_hour = self.config.max_trades_per_hour

        if self.adaptive_regime:
            regime_params = self.adaptive_regime.get_current_parameters()
            max_trades_per_hour = regime_params.max_trades_per_hour

        # Сброс счетчика каждый час
        if (datetime.utcnow() - self.hourly_reset_time).total_seconds() >= 3600:
            self.trade_count_hourly = 0
            self.hourly_reset_time = datetime.utcnow()

        if self.trade_count_hourly >= max_trades_per_hour:
            return (
                False,
                f"Hourly trade limit ({self.trade_count_hourly}/{max_trades_per_hour})",
            )

        # 7. 🔥 КУЛДАУН УБРАН! Теперь торгуем постоянно без пауз!
        # Причина: пользователь хочет больше сделок, агрессивную торговлю
        # Решение: убрать кулдаун, полагаться на hourly trade limit (ARM)

        # Все проверки пройдены
        return True, "OK"

    def record_trade_opened(self, symbol: str):
        """
        Записать открытие сделки.

        Обновляет счетчики и таймстампы.
        """
        self.last_trade_time[symbol] = datetime.utcnow()
        self.trade_count_hourly += 1

    def record_trade_closed(self, net_pnl: float):
        """
        Записать закрытие сделки.

        Обновляет consecutive_losses счетчик.

        Args:
            net_pnl: NET PnL сделки
        """
        if net_pnl < 0:
            self.consecutive_losses += 1
            logger.warning(
                f"📉 Loss #{self.consecutive_losses} of {self.max_consecutive_losses}"
            )

            # Telegram alert при достижении лимита
            if self.consecutive_losses >= self.max_consecutive_losses:
                if self.telegram:
                    asyncio.create_task(
                        self.telegram.send_consecutive_losses_alert(
                            self.consecutive_losses, self.max_consecutive_losses
                        )
                    )
        else:
            if self.consecutive_losses > 0:
                logger.info(
                    f"✅ Win! Consecutive losses reset: {self.consecutive_losses} → 0"
                )
            self.consecutive_losses = 0

    def should_emergency_stop(self, stats: Dict) -> bool:
        """
        Проверка нужна ли экстренная остановка.

        Args:
            stats: Статистика торговли

        Returns:
            bool: True если нужна остановка
        """
        # Max consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            logger.error(
                f"🛑 EMERGENCY STOP: Max consecutive losses reached "
                f"({self.consecutive_losses}/{self.max_consecutive_losses})"
            )

            # Telegram alert
            if self.telegram:
                asyncio.create_task(
                    self.telegram.send_emergency_stop_alert(
                        f"Max consecutive losses: {self.consecutive_losses}/{self.max_consecutive_losses}"
                    )
                )

            return True

        # Critical daily loss
        daily_pnl = stats.get("daily_pnl", 0.0)
        start_balance = stats.get("start_balance", 1000.0)

        if start_balance > 0:
            daily_loss_percent = (daily_pnl / start_balance) * 100

            if daily_loss_percent <= -(
                self.max_daily_loss_percent * 1.5
            ):  # 1.5x критичный уровень
                logger.error(
                    f"🛑 EMERGENCY STOP: Critical daily loss "
                    f"({daily_loss_percent:.2f}% <= -{self.max_daily_loss_percent * 1.5}%)"
                )

                # Telegram alert
                if self.telegram:
                    asyncio.create_task(
                        self.telegram.send_daily_loss_alert(
                            daily_loss_percent,
                            self.max_daily_loss_percent * 1.5,
                            start_balance + daily_pnl,
                        )
                    )

                return True

        return False

    def get_stats(self) -> Dict:
        """Получить статистику рисков"""
        return {
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "trade_count_hourly": self.trade_count_hourly,
            "hourly_reset_time": self.hourly_reset_time.isoformat(),
        }
