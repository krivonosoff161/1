"""
Balance Checker Module - проверка баланса перед открытием позиций.

Предотвращает автоматические займы в SPOT режиме, проверяя наличие
достаточного баланса для открытия LONG (USDT) и SHORT (актив) позиций.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from loguru import logger

from src.models import Balance, OrderSide


@dataclass
class BalanceCheckConfig:
    """Конфигурация модуля проверки баланса."""

    enabled: bool = True
    # Минимальный резерв USDT (процент от баланса, который не используется)
    usdt_reserve_percent: float = 10.0
    # Минимальный баланс актива для открытия SHORT (в USD эквиваленте)
    min_asset_balance_usd: float = 10.0
    # Минимальный баланс USDT для открытия LONG
    min_usdt_balance: float = 10.0
    # Логировать каждую проверку (полезно для отладки)
    log_all_checks: bool = False
    # Адаптивные минимумы (из конфигурации)
    adaptive_minimums: Optional[Dict] = None

    @classmethod
    def from_bot_config(cls, bot_config) -> "BalanceCheckConfig":
        """
        Создает BalanceCheckConfig из BotConfig.

        Args:
            bot_config: Конфигурация бота

        Returns:
            BalanceCheckConfig: Конфигурация для BalanceChecker
        """
        # Получаем адаптивные минимумы из risk секции
        adaptive_minimums = None
        if hasattr(bot_config.risk, "adaptive_minimums"):
            adaptive_minimums = bot_config.risk.adaptive_minimums

        return cls(
            enabled=True,
            usdt_reserve_percent=10.0,
            min_asset_balance_usd=10.0,
            min_usdt_balance=10.0,
            log_all_checks=False,
            adaptive_minimums=adaptive_minimums,
        )


@dataclass
class BalanceCheckResult:
    """Результат проверки баланса."""

    allowed: bool
    reason: str
    available_balance: float
    required_balance: float
    currency: str


class BalanceChecker:
    """
    Проверяет баланс перед открытием позиций.

    Предотвращает:
    - Открытие LONG без достаточного USDT
    - Открытие SHORT без актива на балансе
    - Автоматические займы в SPOT режиме
    """

    def __init__(self, config: BalanceCheckConfig):
        self.config = config
        # Статистика пропущенных сигналов
        self.blocked_signals: Dict[str, int] = {}
        self.total_checks = 0
        self.total_blocked = 0

        logger.info(
            f"Balance Checker initialized: "
            f"USDT reserve={config.usdt_reserve_percent}%, "
            f"min_asset=${config.min_asset_balance_usd}"
        )

    def _get_adaptive_minimum(self, total_balance_usd: float) -> float:
        """
        Возвращает адаптивный минимум на основе общего баланса из конфигурации.

        Args:
            total_balance_usd: Общий баланс в USDT

        Returns:
            Адаптивный минимум для сделки
        """
        if not self.config.adaptive_minimums:
            # Fallback к правильным режимам баланса
            if total_balance_usd < 1500:  # Малый баланс $100-$1500
                return 10.0  # Минимум OKX = $10
            elif total_balance_usd < 2300:  # Средний баланс $1500-$2300
                return 15.0  # Немного больше для среднего баланса
            else:  # Большой баланс $2300+
                return 20.0  # Больше для большого баланса

        # Используем конфигурацию из YAML
        for level_name, level_config in self.config.adaptive_minimums.items():
            if total_balance_usd <= level_config["balance_threshold"]:
                return level_config["minimum_order_usd"]

        # Если баланс больше всех порогов, используем последний уровень
        last_level = list(self.config.adaptive_minimums.values())[-1]
        return last_level["minimum_order_usd"]

    def check_balance(
        self,
        symbol: str,
        side: OrderSide,
        required_amount: float,
        current_price: float,
        balances: list[Balance],
    ) -> BalanceCheckResult:
        """
        Проверяет баланс перед открытием позиции.

        Args:
            symbol: Торговая пара (например, "BTC-USDT")
            side: Сторона сделки (BUY/SELL)
            required_amount: Требуемое количество актива
            current_price: Текущая цена актива
            balances: Список балансов аккаунта

        Returns:
            BalanceCheckResult с результатом проверки
        """
        self.total_checks += 1

        # Извлекаем базовый актив из символа (BTC из BTC-USDT)
        base_asset = symbol.split("-")[0]

        if side == OrderSide.BUY:
            # Для LONG нужен USDT
            return self._check_usdt_balance(
                symbol, required_amount, current_price, balances
            )
        else:  # OrderSide.SELL
            # Для SHORT нужен актив
            return self._check_asset_balance(
                symbol, base_asset, required_amount, current_price, balances
            )

    def _check_usdt_balance(
        self,
        symbol: str,
        required_amount: float,
        current_price: float,
        balances: list[Balance],
    ) -> BalanceCheckResult:
        """
        Проверка баланса USDT для LONG позиции.

        Проверяет что доступного USDT (с учетом резерва) достаточно
        для открытия позиции требуемого размера.
        """
        # Находим баланс USDT
        usdt_balance = next(
            (b for b in balances if b.currency == "USDT"),
            Balance(currency="USDT", free=0.0, used=0.0, total=0.0),
        )

        # Рассчитываем доступный баланс с учетом резерва
        # Используем адаптивный минимум на основе общего баланса
        total_balance_usd = sum(
            b.total for b in balances if b.currency in ["USDT", "BTC", "ETH"]
        )
        adaptive_minimum = self._get_adaptive_minimum(total_balance_usd)

        reserve_amount = max(
            usdt_balance.free * (self.config.usdt_reserve_percent / 100.0),
            adaptive_minimum,  # Адаптивный минимум вместо жесткого
        )
        available_usdt = usdt_balance.free - reserve_amount

        # Требуемая сумма в USDT
        required_usdt = required_amount * current_price

        # Проверяем достаточность средств
        if available_usdt >= required_usdt:
            # ✅ Достаточно средств
            if self.config.log_all_checks:
                logger.debug(
                    f"✅ {symbol} LONG: Balance OK "
                    f"(available ${available_usdt:.2f}, need ${required_usdt:.2f})"
                )

            return BalanceCheckResult(
                allowed=True,
                reason="Sufficient USDT balance",
                available_balance=available_usdt,
                required_balance=required_usdt,
                currency="USDT",
            )
        else:
            # ❌ Недостаточно средств
            self._record_blocked_signal(symbol, "LONG")

            reason = (
                f"Insufficient USDT balance "
                f"(available ${available_usdt:.2f}, need ${required_usdt:.2f})"
            )

            logger.warning(f"⚠️ {symbol} LONG BLOCKED: {reason}")
            logger.info(
                f"💡 TIP: Free USDT: ${usdt_balance.free:.2f}, "
                f"Reserved: ${reserve_amount:.2f} ({self.config.usdt_reserve_percent}%)"
            )

            return BalanceCheckResult(
                allowed=False,
                reason=reason,
                available_balance=available_usdt,
                required_balance=required_usdt,
                currency="USDT",
            )

    def _check_asset_balance(
        self,
        symbol: str,
        asset: str,
        required_amount: float,
        current_price: float,
        balances: list[Balance],
    ) -> BalanceCheckResult:
        """Проверка баланса актива для SHORT позиции."""
        # Находим баланс актива
        asset_balance = next(
            (b for b in balances if b.currency == asset),
            Balance(currency=asset, free=0.0, used=0.0, total=0.0),
        )

        # Проверяем достаточно ли актива
        available_amount = asset_balance.free
        available_usd = available_amount * current_price

        # Используем адаптивный минимум
        total_balance_usd = sum(
            b.total for b in balances if b.currency in ["USDT", "BTC", "ETH"]
        )
        adaptive_minimum = self._get_adaptive_minimum(total_balance_usd)

        if available_amount >= required_amount and available_usd >= adaptive_minimum:
            if self.config.log_all_checks:
                logger.debug(
                    f"✅ {symbol} SHORT: Balance OK "
                    f"(have {available_amount:.6f} {asset} = ${available_usd:.2f})"
                )

            return BalanceCheckResult(
                allowed=True,
                reason=f"Sufficient {asset} balance",
                available_balance=available_amount,
                required_balance=required_amount,
                currency=asset,
            )
        else:
            self._record_blocked_signal(symbol, "SHORT")

            if available_amount < required_amount:
                reason = (
                    f"Insufficient {asset} balance "
                    f"(have {available_amount:.6f}, need {required_amount:.6f})"
                )
            else:
                reason = (
                    f"{asset} balance too small "
                    f"(${available_usd:.2f} < ${adaptive_minimum})"
                )

            logger.warning(f"⚠️ {symbol} SHORT BLOCKED: {reason}")
            logger.info(
                f"💡 TIP: To trade SHORT on {symbol}, you need to hold {asset} "
                f"(buy via LONG signal or manual purchase)"
            )

            return BalanceCheckResult(
                allowed=False,
                reason=reason,
                available_balance=available_amount,
                required_balance=required_amount,
                currency=asset,
            )

    def _record_blocked_signal(self, symbol: str, direction: str) -> None:
        """Записывает статистику заблокированного сигнала."""
        key = f"{symbol}_{direction}"
        self.blocked_signals[key] = self.blocked_signals.get(key, 0) + 1
        self.total_blocked += 1

    def get_statistics(self) -> Dict[str, any]:
        """
        Возвращает статистику работы модуля.

        Returns:
            Словарь со статистикой проверок и блокировок
        """
        return {
            "total_checks": self.total_checks,
            "total_blocked": self.total_blocked,
            "block_rate": (
                (self.total_blocked / self.total_checks * 100)
                if self.total_checks > 0
                else 0.0
            ),
            "blocked_by_pair": self.blocked_signals,
        }

    def log_statistics(self) -> None:
        """Выводит статистику в лог."""
        stats = self.get_statistics()

        if stats["total_checks"] == 0:
            logger.info("📊 Balance Checker: No checks performed yet")
            return

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("📊 BALANCE CHECKER STATISTICS")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"Total checks: {stats['total_checks']}")
        logger.info(f"Total blocked: {stats['total_blocked']}")
        logger.info(f"Block rate: {stats['block_rate']:.1f}%")

        if stats["blocked_by_pair"]:
            logger.info("\nBlocked signals by pair:")
            for key, count in sorted(
                stats["blocked_by_pair"].items(), key=lambda x: x[1], reverse=True
            ):
                logger.info(f"  {key}: {count} signals")

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
