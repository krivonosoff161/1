"""
PnLCalculator - Расчет PnL, комиссий и duration.

Рассчитывает:
- Gross PnL
- Net PnL (с учетом комиссий)
- Duration позиции
- Комиссии entry и exit
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from loguru import logger


class PnLCalculator:
    """
    Калькулятор PnL.

    Рассчитывает прибыль/убыток с учетом комиссий и длительности позиции.
    """

    def __init__(self, client=None, config=None):
        """
        Инициализация PnLCalculator.

        Args:
            client: API клиент (для получения ctVal)
            config: Конфигурация бота (для получения комиссий)
        """
        self.client = client
        self.config = config

        # Комиссии по умолчанию
        self.maker_fee_rate = 0.0002  # 0.02%
        self.taker_fee_rate = 0.0005  # 0.05%

        if config:
            # Загружаем комиссии из конфига
            commission_config = getattr(config, "scalping", {}).get(
                "commission", {}
            ) or getattr(config, "commission", {})
            if isinstance(commission_config, dict):
                self.maker_fee_rate = commission_config.get(
                    "maker_fee_rate", self.maker_fee_rate
                )
                self.taker_fee_rate = commission_config.get(
                    "taker_fee_rate", self.taker_fee_rate
                )
            elif hasattr(commission_config, "maker_fee_rate"):
                self.maker_fee_rate = getattr(
                    commission_config, "maker_fee_rate", self.maker_fee_rate
                )
                self.taker_fee_rate = getattr(
                    commission_config, "taker_fee_rate", self.taker_fee_rate
                )

        logger.info(
            f"✅ PnLCalculator инициализирован "
            f"(maker={self.maker_fee_rate:.4%}, taker={self.taker_fee_rate:.4%})"
        )

    async def calculate_pnl(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size_in_contracts: float,
        entry_time: datetime,
        entry_order_type: str = "market",
        entry_post_only: bool = False,
        exit_order_type: str = "market",
    ) -> Dict[str, Any]:
        """
        Рассчитать PnL для позиции.

        Args:
            symbol: Торговый символ
            side: Направление позиции ("long" или "short")
            entry_price: Цена входа
            exit_price: Цена выхода
            size_in_contracts: Размер позиции в контрактах
            entry_time: Время открытия позиции
            entry_order_type: Тип entry ордера ("market" или "limit")
            entry_post_only: Post-only для entry ордера
            exit_order_type: Тип exit ордера ("market" или "limit")

        Returns:
            Словарь с расчетами PnL
        """
        try:
            # 1. Конвертация размера из контрактов в монеты
            size_in_coins = await self._convert_contracts_to_coins(
                symbol, size_in_contracts
            )

            # 2. Расчет комиссий
            entry_commission, exit_commission = self._calculate_commissions(
                symbol=symbol,
                entry_price=entry_price,
                exit_price=exit_price,
                size_in_coins=size_in_coins,
                entry_order_type=entry_order_type,
                entry_post_only=entry_post_only,
                exit_order_type=exit_order_type,
            )

            total_commission = entry_commission + exit_commission

            # 3. Расчет Gross PnL
            if side.lower() == "long":
                gross_pnl = (exit_price - entry_price) * size_in_coins
            else:  # short
                gross_pnl = (entry_price - exit_price) * size_in_coins

            # 4. Расчет Net PnL
            net_pnl = gross_pnl - total_commission

            # 5. Расчет PnL в процентах
            notional_entry = size_in_coins * entry_price
            pnl_percent_from_price = (net_pnl / notional_entry) * 100

            # 6. Расчет duration
            # ✅ ИСПРАВЛЕНИЕ: Убеждаемся, что entry_time в UTC
            if isinstance(entry_time, datetime):
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                elif entry_time.tzinfo != timezone.utc:
                    entry_time = entry_time.astimezone(timezone.utc)
            duration_sec = (datetime.now(timezone.utc) - entry_time).total_seconds()
            duration_min = duration_sec / 60.0

            return {
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "commission_entry": entry_commission,
                "commission_exit": exit_commission,
                "commission_total": total_commission,
                "pnl_percent_from_price": pnl_percent_from_price,
                "size_in_coins": size_in_coins,
                "size_in_contracts": size_in_contracts,
                "notional_entry": notional_entry,
                "duration_sec": duration_sec,
                "duration_min": duration_min,
            }

        except Exception as e:
            logger.error(
                f"❌ PnLCalculator: Ошибка расчета PnL для {symbol}: {e}", exc_info=True
            )
            raise

    async def _convert_contracts_to_coins(
        self, symbol: str, size_in_contracts: float
    ) -> float:
        """
        Конвертировать размер из контрактов в монеты.

        Args:
            symbol: Торговый символ
            size_in_contracts: Размер в контрактах

        Returns:
            Размер в монетах
        """
        if not self.client:
            logger.warning(
                f"⚠️ PnLCalculator: Клиент не установлен, используем fallback ctVal=0.01 для {symbol}"
            )
            return abs(size_in_contracts) * 0.01

        try:
            details = await self.client.get_instrument_details(symbol)
            ct_val = float(details.get("ctVal", "0.01"))
            size_in_coins = abs(size_in_contracts) * ct_val

            logger.debug(
                f"✅ PnLCalculator: Конвертация для {symbol}: "
                f"{size_in_contracts} контрактов * {ct_val} = {size_in_coins:.6f} монет"
            )

            return size_in_coins

        except Exception as e:
            logger.warning(
                f"⚠️ PnLCalculator: Не удалось получить ctVal для {symbol}: {e}, используем fallback"
            )
            return abs(size_in_contracts) * 0.01  # Fallback

    def _calculate_commissions(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        size_in_coins: float,
        entry_order_type: str,
        entry_post_only: bool,
        exit_order_type: str,
    ) -> Tuple[float, float]:
        """
        Рассчитать комиссии для entry и exit.

        Args:
            symbol: Торговый символ
            entry_price: Цена входа
            exit_price: Цена выхода
            size_in_coins: Размер в монетах
            entry_order_type: Тип entry ордера
            entry_post_only: Post-only для entry
            exit_order_type: Тип exit ордера

        Returns:
            (entry_commission, exit_commission)
        """
        # Entry комиссия
        notional_entry = size_in_coins * entry_price
        if entry_order_type == "limit" and entry_post_only:
            entry_commission_rate = self.maker_fee_rate
        else:
            entry_commission_rate = self.taker_fee_rate

        entry_commission = notional_entry * entry_commission_rate

        # Exit комиссия (обычно taker, так как MARKET ордер)
        notional_exit = size_in_coins * exit_price
        exit_commission_rate = self.taker_fee_rate  # По умолчанию taker
        exit_commission = notional_exit * exit_commission_rate

        return entry_commission, exit_commission
