"""
Futures Position Manager для скальпинг стратегии.

Основные функции:
- Управление открытыми позициями в Futures
- Интеграция с Margin Calculator для контроля маржи
- Автоматическое закрытие позиций по TP/SL
- Мониторинг PnL и рисков
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig, ScalpingConfig
from src.strategies.modules.margin_calculator import MarginCalculator


class FuturesPositionManager:
    """
    Менеджер позиций для Futures торговли

    Функции:
    - Управление открытыми позициями
    - Мониторинг маржи и рисков
    - Автоматическое закрытие позиций
    - Интеграция с Margin Calculator
    """

    def __init__(
        self,
        config: BotConfig,
        client: OKXFuturesClient,
        margin_calculator: MarginCalculator,
    ):
        """
        Инициализация Futures Position Manager

        Args:
            config: Конфигурация бота
            client: Futures клиент
            margin_calculator: Калькулятор маржи
        """
        self.config = config
        self.scalping_config = config.scalping
        self.client = client
        self.margin_calculator = margin_calculator
        self.symbol_profiles: Dict[
            str, Dict[str, Any]
        ] = {}  # ✅ НОВОЕ: Для per-symbol TP
        self.orchestrator = None  # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Ссылка на orchestrator для доступа к trailing_sl_by_symbol

        # Состояние
        self.is_initialized = False
        self.active_positions = {}
        self.position_history = []
        self.management_stats = {
            "total_positions": 0,
            "closed_positions": 0,
            "tp_closed": 0,
            "sl_closed": 0,
            "manual_closed": 0,
            "total_pnl": 0.0,
        }

        logger.info("FuturesPositionManager инициализирован")

    def set_symbol_profiles(self, symbol_profiles: Dict[str, Dict[str, Any]]):
        """✅ НОВОЕ: Устанавливает symbol_profiles для per-symbol TP"""
        self.symbol_profiles = symbol_profiles
        logger.debug(
            f"✅ symbol_profiles установлен в position_manager ({len(symbol_profiles)} символов)"
        )

    def set_orchestrator(self, orchestrator):
        """✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Устанавливает ссылку на orchestrator для доступа к trailing_sl_by_symbol"""
        self.orchestrator = orchestrator
        logger.debug("✅ Orchestrator установлен в position_manager")

    async def initialize(self):
        """Инициализация менеджера позиций"""
        try:
            # Получение текущих позиций
            positions = await self.client.get_positions()

            # Инициализация активных позиций
            for position in positions:
                symbol = position.get("instId", "").replace("-SWAP", "")
                size = float(position.get("pos", "0"))
                if size != 0:
                    self.active_positions[symbol] = position

            logger.info(f"✅ Инициализировано позиций: {len(self.active_positions)}")
            self.is_initialized = True

        except Exception as e:
            logger.error(f"Ошибка инициализации FuturesPositionManager: {e}")
            raise

    async def manage_position(self, position: Dict[str, Any]):
        """
        Управление отдельной позицией

        Args:
            position: Данные позиции
        """
        if not self.is_initialized:
            logger.warning("PositionManager не инициализирован")
            return

        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")

            if size == 0:
                # Позиция закрыта
                if symbol in self.active_positions:
                    await self._handle_position_closed(symbol)
                return

            # Обновление активных позиций
            self.active_positions[symbol] = position

            # Проверка безопасности позиции
            await self._check_position_safety(position)

            # Проверка TP/SL
            # ⚠️ ВАЖНО: Фиксированный SL отключен, когда используется TrailingSL
            # TrailingSL проверяется в orchestrator._update_trailing_stop_loss
            # Здесь проверяем только TP (Take Profit)
            await self._check_tp_only(position)

            # Обновление статистики
            await self._update_position_stats(position)

        except Exception as e:
            logger.error(f"Ошибка управления позицией {symbol}: {e}")

    async def _check_position_safety(self, position: Dict[str, Any]):
        """Проверка безопасности позиции"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))
            # ✅ ИСПРАВЛЕНИЕ: Используем leverage из конфига, а не из позиции на бирже
            # На бирже может быть установлен старый leverage (3x), но расчеты должны использовать leverage из конфига (5x)
            leverage_from_position = int(position.get("lever", "0"))
            leverage = (
                getattr(self.scalping_config, "leverage", None)
                or leverage_from_position
                or 3
            )
            if leverage_from_position != leverage:
                logger.debug(
                    f"📊 Leverage: биржа={leverage_from_position}x, конфиг={leverage}x, используем {leverage}x для расчетов"
                )

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для изолированной маржи получаем equity через get_margin_info!
            # Это правильный баланс для данной позиции, а не общий баланс аккаунта
            try:
                margin_info = await self.client.get_margin_info(symbol)
                equity = margin_info.get("equity", 0)

                # Если equity не найден в margin_info, пытаемся получить из самой позиции
                if equity == 0:
                    # Проверяем, есть ли 'eq' или другие поля в самой позиции
                    if "eq" in position and position["eq"]:
                        try:
                            equity = float(position["eq"])
                            logger.debug(
                                f"✅ equity получен из position['eq'] для {symbol}: {equity:.2f}"
                            )
                        except (ValueError, TypeError):
                            pass

                    # Если все еще 0, используем общий баланс как fallback
                    if equity == 0:
                        equity = await self.client.get_balance()
                        logger.warning(
                            f"⚠️ equity не найден через get_margin_info для {symbol}, используем общий баланс: {equity:.2f}"
                        )
            except Exception as e:
                # Fallback при ошибке - сначала пытаемся из позиции
                equity = 0
                try:
                    if "eq" in position and position["eq"]:
                        equity = float(position["eq"])
                        logger.debug(
                            f"✅ equity получен из position['eq'] (fallback) для {symbol}: {equity:.2f}"
                        )
                except (ValueError, TypeError):
                    pass

                if equity == 0:
                    equity = await self.client.get_balance()
                    logger.warning(
                        f"⚠️ Ошибка получения equity для {symbol}: {e}, используем общий баланс: {equity:.2f}"
                    )

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: size из API в контрактах!
            # Нужно получить ctVal для правильного расчета стоимости
            try:
                details = await self.client.get_instrument_details(symbol)
                ct_val = details.get("ctVal", 0.01)  # По умолчанию для BTC/ETH
                # Реальный размер в монетах
                size_in_coins = abs(size) * ct_val
                # Стоимость позиции в USD
                position_value = size_in_coins * current_price
                logger.debug(
                    f"📊 Расчет position_value для {symbol}: "
                    f"size={size} контрактов, ctVal={ct_val}, "
                    f"size_in_coins={size_in_coins:.6f}, "
                    f"current_price={current_price:.2f}, "
                    f"position_value={position_value:.2f} USD"
                )
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка получения ctVal для {symbol}, используем приблизительный расчет: {e}"
                )
                # Fallback: предполагаем что size уже в монетах (для совместимости)
                size_in_coins = abs(size)
                position_value = size_in_coins * current_price
                logger.warning(
                    f"⚠️ Fallback расчет для {symbol}: size_in_coins={size_in_coins:.6f}, position_value={position_value:.2f} USD"
                )

            # Проверка безопасности через Margin Calculator
            # ⚠️ Используем equity из позиции, а не общий баланс!
            logger.debug(
                f"🔍 Проверка безопасности {symbol}: "
                f"position_value={position_value:.2f}, equity={equity:.2f}, "
                f"current_price={current_price:.2f}, entry_price={entry_price:.2f}, "
                f"leverage={leverage}x"
            )
            is_safe, details = self.margin_calculator.is_position_safe(
                position_value,
                equity,  # ✅ Используем equity из позиции!
                current_price,
                entry_price,
                side,
                leverage,
                safety_threshold=1.5,
            )

            if not is_safe:
                margin_ratio = details["margin_ratio"]
                pnl = details.get("pnl", 0)
                available_margin = details.get("available_margin", 0)
                margin_used = details.get("margin_used", 0)

                logger.warning(
                    f"⚠️ Позиция {symbol} небезопасна: маржа {margin_ratio:.1f}%"
                )

                # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА от ложных срабатываний (как в LiquidationGuard):
                # Если margin_ratio <= 1.5 и PnL небольшой - это ошибка расчета, а не реальный риск
                # Это особенно часто происходит сразу после открытия позиции
                if margin_ratio <= 1.5 and abs(pnl) < 10:
                    logger.warning(
                        f"⚠️ ПОДОЗРИТЕЛЬНОЕ состояние для {symbol} в PositionManager: "
                        f"margin_ratio={margin_ratio:.2f}, available_margin={available_margin:.2f}, "
                        f"pnl={pnl:.2f}, equity={equity:.2f}. "
                        f"Возможна ошибка расчета (позиция только что открыта?), пропускаем автозакрытие."
                    )
                    return  # Пропускаем автозакрытие

                # 🛡️ ЗАЩИТА 2: Если margin_ratio = 0.0 или очень близок к нулю - это почти всегда ошибка
                if margin_ratio <= 0.5 and equity > 0:
                    logger.warning(
                        f"⚠️ ПОДОЗРИТЕЛЬНОЕ состояние для {symbol} в PositionManager: "
                        f"margin_ratio={margin_ratio:.2f} слишком низкий для реальной позиции. "
                        f"Возможна ошибка расчета (equity={equity:.2f}, margin_used={margin_used:.2f}), "
                        f"пропускаем автозакрытие."
                    )
                    return  # Пропускаем автозакрытие

                # 🛡️ ЗАЩИТА 3: Если available_margin сильно отрицательный, но PnL небольшой - ошибка
                if available_margin < -1000 and abs(pnl) < 100:
                    logger.warning(
                        f"⚠️ ПОДОЗРИТЕЛЬНОЕ состояние для {symbol} в PositionManager: "
                        f"margin_ratio={margin_ratio:.2f}, available_margin={available_margin:.2f}, "
                        f"pnl={pnl:.2f}. Возможна ошибка расчета, пропускаем автозакрытие."
                    )
                    return  # Пропускаем автозакрытие

                # Дополнительные действия при низкой марже (только если это реальный риск!)
                # ⚠️ ВНИМАНИЕ: Не закрываем автоматически, если margin_ratio отрицательный
                # (это может быть из-за ошибки расчета - исправлено выше)
                if margin_ratio < 1.2 and margin_ratio > 0:
                    logger.warning(
                        f"⚠️ Позиция {symbol} имеет низкую маржу: {margin_ratio:.2f}%. Закрытие..."
                    )
                    await self._emergency_close_position(position)
                elif margin_ratio <= 0:
                    logger.warning(
                        f"⚠️ Позиция {symbol} имеет некорректный margin_ratio: {margin_ratio:.2f}%. Пропускаем автозакрытие."
                    )

        except Exception as e:
            logger.error(f"Ошибка проверки безопасности позиции: {e}")

    async def _check_tp_sl(self, position: Dict[str, Any]):
        """Проверка Take Profit и Stop Loss (DEPRECATED - используется _check_tp_only)"""
        # Этот метод оставлен для совместимости, но теперь используется _check_tp_only
        await self._check_tp_only(position)

    async def _check_tp_only(self, position: Dict[str, Any]):
        """Проверка только Take Profit (SL управляется TrailingSL в orchestrator)"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            side = position.get("posSide", "long")
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))
            # ✅ ИСПРАВЛЕНИЕ: Используем leverage из конфига, а не из позиции на бирже
            # На бирже может быть установлен старый leverage (3x), но расчеты должны использовать leverage из конфига (5x)
            leverage_from_position = int(position.get("lever", "0"))
            leverage = (
                getattr(self.scalping_config, "leverage", None)
                or leverage_from_position
                or 3
            )
            if leverage_from_position != leverage:
                logger.debug(
                    f"📊 Leverage: биржа={leverage_from_position}x, конфиг={leverage}x, используем {leverage}x для расчетов"
                )

            if size == 0:
                return

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: PnL% должен считаться от МАРЖИ, а не от цены входа!
            # Биржа показывает PnL% от маржи (например, 0.89% для ETH), а не от цены (0.30%)
            # Поэтому TP должен сравниваться с PnL% от маржи, иначе позиции не закрываются!

            # Получаем маржу позиции
            try:
                margin_info = await self.client.get_margin_info(symbol)
                margin_used = margin_info.get("margin", 0)
                # OKX API использует "upl" для unrealizedPnl
                unrealized_pnl = margin_info.get(
                    "upl", margin_info.get("unrealized_pnl", 0)
                )

                # Если margin_info не дает нужные данные, считаем из position
                if margin_used == 0:
                    # Пытаемся получить из position или рассчитать
                    if "margin" in position:
                        margin_used = float(position["margin"])
                    elif "imr" in position:
                        margin_used = float(
                            position["imr"]
                        )  # Initial Margin Requirement
                    else:
                        # Рассчитываем маржу из размера позиции
                        # position_value = size_in_coins * entry_price
                        # margin = position_value / leverage
                        # Для этого нужно получить ctVal
                        try:
                            inst_details = await self.client.get_instrument_details(
                                symbol
                            )
                            ct_val = float(inst_details.get("ctVal", "0.01"))
                            size_in_coins = abs(size) * ct_val
                            position_value = size_in_coins * entry_price
                            margin_used = position_value / leverage
                        except Exception as e:
                            logger.debug(
                                f"Не удалось рассчитать margin для {symbol}: {e}"
                            )
                            # Fallback: используем старый метод (процент от цены)
                            if side.lower() == "long":
                                pnl_percent = (
                                    (current_price - entry_price) / entry_price * 100
                                )
                            else:
                                pnl_percent = (
                                    (entry_price - current_price) / entry_price * 100
                                )
                            logger.warning(
                                f"⚠️ Используем fallback расчет PnL% для {symbol}: {pnl_percent:.2f}% (от цены, а не от маржи)"
                            )
                            tp_percent = self.scalping_config.tp_percent
                            if pnl_percent >= tp_percent:
                                logger.info(
                                    f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}%"
                                )
                                await self._close_position_by_reason(position, "tp")
                            return
            except Exception as e:
                logger.debug(
                    f"Не удалось получить margin_info для {symbol}: {e}, используем fallback"
                )
                margin_used = 0
                unrealized_pnl = 0

            # Если получили margin, считаем PnL% от маржи
            if margin_used > 0:
                # Получаем unrealizedPnl из position или margin_info
                if unrealized_pnl == 0:
                    if "upl" in position:
                        unrealized_pnl = float(position["upl"])
                    elif "unrealizedPnl" in position:
                        unrealized_pnl = float(position["unrealizedPnl"])
                    else:
                        # Рассчитываем PnL вручную
                        try:
                            inst_details = await self.client.get_instrument_details(
                                symbol
                            )
                            ct_val = float(inst_details.get("ctVal", "0.01"))
                            size_in_coins = abs(size) * ct_val
                            if side.lower() == "long":
                                unrealized_pnl = size_in_coins * (
                                    current_price - entry_price
                                )
                            else:
                                unrealized_pnl = size_in_coins * (
                                    entry_price - current_price
                                )
                        except Exception:
                            # Последний fallback: используем процент от цены
                            if side.lower() == "long":
                                pnl_percent = (
                                    (current_price - entry_price) / entry_price * 100
                                )
                            else:
                                pnl_percent = (
                                    (entry_price - current_price) / entry_price * 100
                                )
                            logger.warning(
                                f"⚠️ Fallback расчет PnL% для {symbol}: {pnl_percent:.2f}%"
                            )
                            tp_percent = self.scalping_config.tp_percent
                            if pnl_percent >= tp_percent:
                                logger.info(
                                    f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}%"
                                )
                                await self._close_position_by_reason(position, "tp")
                            return

                # ✅ ПРАВИЛЬНЫЙ РАСЧЕТ: PnL% от маржи (как на бирже!)
                pnl_percent = (unrealized_pnl / margin_used) * 100
                logger.debug(
                    f"📊 TP проверка {symbol}: PnL=${unrealized_pnl:.2f}, "
                    f"margin=${margin_used:.2f}, PnL%={pnl_percent:.2f}% (от маржи)"
                )
            else:
                # Fallback: если margin не получили, используем процент от цены
                if side.lower() == "long":
                    pnl_percent = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_percent = (entry_price - current_price) / entry_price * 100
                logger.warning(
                    f"⚠️ Fallback: PnL% для {symbol} считаем от цены: {pnl_percent:.2f}%"
                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверка трейлинг стоп-лосс ПЕРЕД TP
            # Если трейлинг стоп-лосс активен (позиция в прибыли и достиг min_profit_to_close),
            # то TP отключен (трейлинг стоп-лосс имеет приоритет)
            commission_rate = 0.0009  # 0.09% на круг (0.045% вход + 0.045% выход)
            trailing_sl_active = False
            min_profit_to_close = None

            # Получаем трейлинг стоп-лосс из orchestrator (если доступен)
            if hasattr(self, "orchestrator") and self.orchestrator:
                trailing_sl_by_symbol = getattr(
                    self.orchestrator, "trailing_sl_by_symbol", {}
                )
                if symbol in trailing_sl_by_symbol:
                    tsl = trailing_sl_by_symbol[symbol]
                    # Получаем текущую прибыль (net с комиссией)
                    profit_pct_net = tsl.get_profit_pct(
                        current_price, include_fees=True
                    )
                    min_profit_to_close = getattr(tsl, "min_profit_to_close", None)

                    # Если позиция в прибыли и достиг минимального профита для трейлинга
                    # ⚠️ ВАЖНО: profit_pct_net и min_profit_to_close оба в долях (0.001 = 0.1%)
                    if profit_pct_net > 0 and min_profit_to_close is not None:
                        if profit_pct_net >= min_profit_to_close:
                            # Трейлинг стоп-лосс активен - TP отключен (трейлинг стоп-лосс имеет приоритет)
                            trailing_sl_active = True
                            logger.debug(
                                f"📊 {symbol} трейлинг стоп-лосс активен "
                                f"(profit={profit_pct_net:.3%} >= {min_profit_to_close:.3%}), "
                                f"TP отключен (трейлинг стоп-лосс имеет приоритет)"
                            )
                            return  # Не проверяем TP, трейлинг стоп-лосс имеет приоритет

            # ✅ НОВОЕ: Проверка Take Profit с поддержкой per-symbol и per-regime TP
            tp_percent = self.scalping_config.tp_percent  # Глобальный (fallback)

            # Получаем режим из позиции (сохранен при открытии)
            regime = position.get("regime") or self.active_positions.get(
                symbol, {}
            ).get("regime")

            # Получаем tp_percent для символа и режима (если есть в symbol_profiles)
            if symbol and self.symbol_profiles:
                symbol_profile = self.symbol_profiles.get(symbol, {})
                if symbol_profile:
                    # Конвертируем в dict если нужно
                    if not isinstance(symbol_profile, dict):
                        # Если это Pydantic модель или другой объект, пробуем разные способы
                        if hasattr(symbol_profile, "dict"):
                            symbol_dict = symbol_profile.dict()
                        elif hasattr(symbol_profile, "__dict__"):
                            symbol_dict = dict(symbol_profile.__dict__)
                        else:
                            symbol_dict = {}
                    else:
                        symbol_dict = symbol_profile

                    # 1. ✅ ПРИОРИТЕТ 1: Per-regime TP (если режим определен)
                    if regime:
                        regime_lower = (
                            regime.lower()
                            if isinstance(regime, str)
                            else str(regime).lower()
                        )
                        regime_profile = symbol_dict.get(regime_lower, {})

                        # Конвертируем regime_profile в dict если нужно
                        if not isinstance(regime_profile, dict):
                            if hasattr(regime_profile, "dict"):
                                regime_profile = regime_profile.dict()
                            elif hasattr(regime_profile, "__dict__"):
                                regime_profile = dict(regime_profile.__dict__)
                            else:
                                regime_profile = {}

                        regime_tp_percent = regime_profile.get("tp_percent")
                        if regime_tp_percent is not None:
                            # ✅ ИСПРАВЛЕНИЕ: Проверяем тип перед конвертацией в float
                            if isinstance(regime_tp_percent, (int, float)):
                                tp_percent = float(regime_tp_percent)
                                logger.debug(
                                    f"📊 Per-regime TP для {symbol} ({regime}): {tp_percent}% "
                                    f"(глобальный: {self.scalping_config.tp_percent}%)"
                                )
                            elif isinstance(regime_tp_percent, str):
                                try:
                                    tp_percent = float(regime_tp_percent)
                                    logger.debug(
                                        f"📊 Per-regime TP для {symbol} ({regime}): {tp_percent}% "
                                        f"(глобальный: {self.scalping_config.tp_percent}%)"
                                    )
                                except (ValueError, TypeError):
                                    logger.warning(
                                        f"⚠️ Не удалось конвертировать regime_tp_percent в float для {symbol} ({regime}): {regime_tp_percent}"
                                    )
                            else:
                                logger.warning(
                                    f"⚠️ regime_tp_percent для {symbol} ({regime}) имеет неожиданный тип: {type(regime_tp_percent)}, значение: {regime_tp_percent}"
                                )

                    # 2. ✅ ПРИОРИТЕТ 2: Per-symbol TP (fallback, если режим не определен)
                    if tp_percent == self.scalping_config.tp_percent:
                        symbol_tp_percent = symbol_dict.get("tp_percent")
                        if symbol_tp_percent is not None:
                            # ✅ ИСПРАВЛЕНИЕ: Проверяем тип перед конвертацией в float
                            if isinstance(symbol_tp_percent, (int, float)):
                                tp_percent = float(symbol_tp_percent)
                                logger.debug(
                                    f"📊 Per-symbol TP для {symbol}: {tp_percent}% "
                                    f"(глобальный: {self.scalping_config.tp_percent}%)"
                                )
                            elif isinstance(symbol_tp_percent, str):
                                try:
                                    tp_percent = float(symbol_tp_percent)
                                    logger.debug(
                                        f"📊 Per-symbol TP для {symbol}: {tp_percent}% "
                                        f"(глобальный: {self.scalping_config.tp_percent}%)"
                                    )
                                except (ValueError, TypeError):
                                    logger.warning(
                                        f"⚠️ Не удалось конвертировать symbol_tp_percent в float для {symbol}: {symbol_tp_percent}"
                                    )
                            else:
                                logger.warning(
                                    f"⚠️ symbol_tp_percent для {symbol} имеет неожиданный тип: {type(symbol_tp_percent)}, значение: {symbol_tp_percent}"
                                )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: TP должен быть выше минимального профита трейлинг стоп-лосс + комиссия
            # Если трейлинг стоп-лосс еще не активен (не достиг min_profit_to_close), то TP может сработать,
            # но должен быть выше min_profit_to_close + комиссия + buffer
            # ⚠️ ВАЖНО: min_profit_to_close в долях (0.001 = 0.1%), tp_percent в процентах (1.0 = 1%)
            if (
                not trailing_sl_active
                and min_profit_to_close is not None
                and pnl_percent > 0
            ):
                min_profit_to_close_pct = (
                    min_profit_to_close * 100
                )  # Конвертируем в проценты для сравнения с tp_percent
                commission_pct = commission_rate * 100  # Комиссия в процентах (0.09%)
                buffer_pct = 0.1  # Запас 0.1% (для безопасности)
                min_tp_percent = min_profit_to_close_pct + commission_pct + buffer_pct

                if tp_percent < min_tp_percent:
                    # TP слишком низкий - поднимаем до минимума
                    original_tp = tp_percent
                    tp_percent = min_tp_percent
                    logger.debug(
                        f"📊 {symbol} TP поднят с {original_tp:.2f}% до {tp_percent:.2f}% "
                        f"(минимум для трейлинга: min_profit={min_profit_to_close_pct:.2f}% + комиссия={commission_pct:.2f}% + запас={buffer_pct:.2f}% = {min_tp_percent:.2f}%)"
                    )

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Учитываем комиссию при проверке TP
            # TP должен быть достаточно высоким, чтобы покрыть комиссию и дать прибыль
            tp_percent_with_commission = tp_percent + (commission_rate * 100)

            if pnl_percent >= tp_percent_with_commission:
                # Учитываем комиссию при закрытии
                net_pnl_percent = pnl_percent - (commission_rate * 100)
                if net_pnl_percent > 0:
                    logger.info(
                        f"🎯 TP достигнут для {symbol}: {pnl_percent:.2f}% "
                        f"(TP={tp_percent:.2f}%, net после комиссии: {net_pnl_percent:.2f}%, "
                        f"PnL=${unrealized_pnl:.2f}, margin=${margin_used:.2f})"
                    )
                    await self._close_position_by_reason(position, "tp")
                    return
                else:
                    # После комиссии убыток - не закрываем по TP
                    logger.debug(
                        f"📊 {symbol} TP достигнут, но после комиссии убыток: "
                        f"{pnl_percent:.2f}% - {commission_rate * 100:.2f}% = {net_pnl_percent:.2f}%, "
                        f"не закрываем"
                    )
            else:
                logger.debug(
                    f"📊 {symbol} PnL={pnl_percent:.2f}% < TP={tp_percent:.2f}% "
                    f"(с комиссией: {tp_percent_with_commission:.2f}%, нужно еще {tp_percent_with_commission - pnl_percent:.2f}%)"
                )

            # ⚠️ Stop Loss отключен - используется TrailingSL из orchestrator
            # TrailingSL более гибкий и учитывает тренд/режим рынка

        except Exception as e:
            logger.error(f"Ошибка проверки TP: {e}")

    async def _close_position_by_reason(self, position: Dict[str, Any], reason: str):
        """Закрытие позиции по причине"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Проверяем актуальное состояние позиции на бирже
            # перед закрытием, так как position может быть устаревшим
            actual_positions = await self.client.get_positions(symbol)

            # Ищем актуальную позицию
            actual_position = None
            for pos in actual_positions:
                inst_id = pos.get("instId", "").replace("-SWAP", "")
                if inst_id == symbol:
                    size = float(pos.get("pos", "0"))
                    if size != 0:  # Позиция еще открыта
                        actual_position = pos
                        break

            # Если позиция уже закрыта, просто удаляем из активных
            if actual_position is None:
                logger.info(
                    f"⚠️ Позиция {symbol} уже закрыта на бирже, удаляем из активных"
                )
                if symbol in self.active_positions:
                    del self.active_positions[symbol]
                return

            size = float(actual_position.get("pos", "0"))
            side = actual_position.get("posSide", "long")

            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем финальный PnL перед закрытием
            final_pnl = 0.0
            try:
                # Пробуем разные варианты названий полей для unrealized PnL
                if "upl" in actual_position and actual_position.get("upl"):
                    final_pnl = float(actual_position["upl"])
                elif "uPnl" in actual_position and actual_position.get("uPnl"):
                    final_pnl = float(actual_position["uPnl"])
                elif "unrealizedPnl" in actual_position and actual_position.get(
                    "unrealizedPnl"
                ):
                    final_pnl = float(actual_position["unrealizedPnl"])
            except (ValueError, TypeError):
                pass

            logger.info(
                f"🔄 Закрытие позиции {symbol} по причине: {reason}, размер={size} контрактов, PnL={final_pnl:.2f} USDT"
            )

            # Определение стороны закрытия
            close_side = "sell" if side.lower() == "long" else "buy"

            # Размещение рыночного ордера на закрытие
            # ⚠️ size из API уже в контрактах, поэтому size_in_contracts=True
            # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем reduceOnly=True для закрытия
            result = await self.client.place_futures_order(
                symbol=symbol,
                side=close_side,
                size=abs(size),
                order_type="market",
                size_in_contracts=True,  # size из API уже в контрактах
                reduce_only=True,  # ✅ КРИТИЧЕСКОЕ: Только закрытие, не открытие новой позиции
            )

            if result.get("code") == "0":
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Записываем финальный PnL в лог для анализатора
                logger.info(
                    f"✅ Позиция {symbol} закрыта по {reason}, PnL = {final_pnl:+.2f} USDT"
                )

                # Обновление статистики
                self._update_close_stats(reason)

                # Удаление из активных позиций
                if symbol in self.active_positions:
                    del self.active_positions[symbol]
                    logger.debug(
                        f"✅ Позиция {symbol} удалена из active_positions (position_manager)"
                    )

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Удаляем позицию из orchestrator.active_positions и trailing_sl_by_symbol
                # для синхронизации состояния после закрытия по TP
                if hasattr(self, "orchestrator") and self.orchestrator:
                    if symbol in self.orchestrator.active_positions:
                        del self.orchestrator.active_positions[symbol]
                        logger.debug(
                            f"✅ Позиция {symbol} удалена из orchestrator.active_positions"
                        )
                    if symbol in self.orchestrator.trailing_sl_by_symbol:
                        self.orchestrator.trailing_sl_by_symbol[symbol].reset()
                        del self.orchestrator.trailing_sl_by_symbol[symbol]
                        logger.debug(
                            f"✅ TrailingStopLoss для {symbol} удален из orchestrator"
                        )
            else:
                error_msg = result.get("msg", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка закрытия позиции {symbol}: {error_msg}")

        except Exception as e:
            logger.error(f"Ошибка закрытия позиции: {e}")

    async def _emergency_close_position(self, position: Dict[str, Any]):
        """Экстренное закрытие позиции"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            logger.critical(f"🚨 ЭКСТРЕННОЕ ЗАКРЫТИЕ ПОЗИЦИИ: {symbol}")

            await self._close_position_by_reason(position, "emergency")

        except Exception as e:
            logger.error(f"Ошибка экстренного закрытия позиции: {e}")

    async def _handle_position_closed(self, symbol: str):
        """Обработка закрытой позиции"""
        try:
            if symbol in self.active_positions:
                position = self.active_positions[symbol]

                # Сохранение в историю
                self.position_history.append(
                    {
                        "symbol": symbol,
                        "position": position,
                        "close_time": datetime.now(),
                        "close_reason": "manual",
                    }
                )

                # Удаление из активных позиций
                del self.active_positions[symbol]

                logger.info(f"📊 Позиция {symbol} закрыта")

        except Exception as e:
            logger.error(f"Ошибка обработки закрытой позиции: {e}")

    async def _update_position_stats(self, position: Dict[str, Any]):
        """Обновление статистики позиции"""
        try:
            symbol = position.get("instId", "").replace("-SWAP", "")
            size = float(position.get("pos", "0"))
            entry_price = float(position.get("avgPx", "0"))
            current_price = float(position.get("markPx", "0"))
            side = position.get("posSide", "long")

            if size == 0:
                return

            # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: size из API в КОНТРАКТАХ!
            # Нужно получить ctVal для конвертации в монеты перед расчетом PnL
            try:
                details = await self.client.get_instrument_details(symbol)
                ct_val = details.get("ctVal", 0.01)  # По умолчанию для BTC/ETH
                # Реальный размер в монетах
                size_in_coins = abs(size) * ct_val
            except Exception as e:
                logger.warning(
                    f"⚠️ Ошибка получения ctVal для {symbol}, используем fallback: {e}"
                )
                # Fallback: предполагаем что size уже в монетах (для совместимости)
                size_in_coins = abs(size)

            # Расчет текущего PnL (теперь с правильным размером в монетах)
            if side.lower() == "long":
                pnl = (current_price - entry_price) * size_in_coins
            else:  # short
                pnl = (entry_price - current_price) * size_in_coins

            # Обновление общего PnL
            self.management_stats["total_pnl"] += pnl

            logger.debug(
                f"📈 Позиция {symbol}: PnL = {pnl:.2f} USDT (size={size} контрактов = {size_in_coins:.6f} монет)"
            )

        except Exception as e:
            logger.error(f"Ошибка обновления статистики позиции: {e}")

    def _update_close_stats(self, reason: str):
        """Обновление статистики закрытия"""
        try:
            self.management_stats["closed_positions"] += 1

            if reason == "tp":
                self.management_stats["tp_closed"] += 1
            elif reason == "sl":
                self.management_stats["sl_closed"] += 1
            elif reason == "emergency":
                self.management_stats["manual_closed"] += 1

        except Exception as e:
            logger.error(f"Ошибка обновления статистики закрытия: {e}")

    async def close_position_manually(self, symbol: str) -> Dict[str, Any]:
        """
        ✅ РУЧНОЕ ЗАКРЫТИЕ ПОЗИЦИИ (для TrailingSL)

        Закрывает позицию через API без конфликтов с OCO
        """
        try:
            # Получаем информацию о позиции с биржи
            # ⚠️ ИСПРАВЛЕНИЕ: get_positions() возвращает СПИСОК, не dict!
            positions = await self.client.get_positions(symbol)

            # Проверяем, что positions это список
            if not isinstance(positions, list) or len(positions) == 0:
                logger.warning(f"Позиция {symbol} не найдена на бирже (список пустой)")
                return {"success": False, "error": "Позиция не найдена"}

            # Ищем нужную позицию в списке
            for pos_data in positions:
                inst_id = pos_data.get("instId", "").replace("-SWAP", "")
                if inst_id != symbol:
                    continue

                size = float(pos_data.get("pos", "0"))
                if size == 0:
                    logger.warning(f"Размер позиции {symbol} = 0, позиция уже закрыта")
                    return {
                        "success": True,
                        "symbol": symbol,
                        "message": "Позиция уже закрыта",
                    }

                side = pos_data.get("posSide", "long")

                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Получаем финальный PnL перед закрытием
                final_pnl = 0.0
                try:
                    # Пробуем разные варианты названий полей для unrealized PnL
                    if "upl" in pos_data and pos_data.get("upl"):
                        final_pnl = float(pos_data["upl"])
                    elif "uPnl" in pos_data and pos_data.get("uPnl"):
                        final_pnl = float(pos_data["uPnl"])
                    elif "unrealizedPnl" in pos_data and pos_data.get("unrealizedPnl"):
                        final_pnl = float(pos_data["unrealizedPnl"])
                except (ValueError, TypeError):
                    pass

                logger.info(
                    f"🔄 Закрытие позиции {symbol} {side} размер={size} контрактов, PnL={final_pnl:.2f} USDT"
                )

                # Определение стороны закрытия
                close_side = "sell" if side.lower() == "long" else "buy"

                # ✅ Размещаем рыночный ордер на закрытие
                # ⚠️ size из API уже в контрактах, поэтому size_in_contracts=True
                # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Для закрытия позиции используем reduceOnly=True
                # Это гарантирует, что ордер не откроет новую позицию, а только закроет существующую
                result = await self.client.place_futures_order(
                    symbol=symbol,
                    side=close_side,
                    size=abs(size),
                    order_type="market",
                    size_in_contracts=True,  # size из API уже в контрактах
                    reduce_only=True,  # ✅ КРИТИЧЕСКОЕ: Только закрытие, не открытие новой позиции
                )

                if result.get("code") == "0":
                    # ✅ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Записываем финальный PnL в лог для анализатора
                    logger.info(
                        f"✅ Позиция {symbol} закрыта через API, PnL = {final_pnl:+.2f} USDT"
                    )
                    # Удаляем из активных позиций
                    if symbol in self.active_positions:
                        del self.active_positions[symbol]
                    return {"success": True, "symbol": symbol}
                else:
                    error_msg = result.get("msg", "Неизвестная ошибка")
                    error_code = result.get("data", [{}])[0].get("sCode", "")

                    # Если позиция уже закрыта или не найдена - это не ошибка
                    if (
                        error_code in ["51008", "51000"]
                        and "insufficient" in error_msg.lower()
                    ):
                        logger.warning(
                            f"⚠️ Позиция {symbol} возможно уже закрыта или недостаточно маржи. Проверяем состояние..."
                        )
                        # Проверяем, закрыта ли позиция
                        await asyncio.sleep(0.5)  # Небольшая задержка
                        check_positions = await self.client.get_positions(symbol)
                        found_open = False
                        for pos in check_positions:
                            if float(pos.get("pos", "0")) != 0:
                                found_open = True
                                break
                        if not found_open:
                            logger.info(f"✅ Позиция {symbol} действительно уже закрыта")
                            if symbol in self.active_positions:
                                del self.active_positions[symbol]
                            return {
                                "success": True,
                                "symbol": symbol,
                                "message": "Позиция уже была закрыта",
                            }

                    logger.error(
                        f"❌ Ошибка закрытия {symbol}: {error_msg} (код: {error_code})"
                    )
                    return {"success": False, "error": error_msg}

            return {"success": False, "error": "Позиция не найдена в списке"}

        except Exception as e:
            logger.error(f"Ошибка ручного закрытия позиции: {e}")
            return {"success": False, "error": str(e)}

    async def close_all_positions(self) -> Dict[str, Any]:
        """Закрытие всех позиций"""
        try:
            closed_count = 0
            errors = []

            symbols_to_close = list(self.active_positions.keys())

            for symbol in symbols_to_close:
                result = await self.close_position_manually(symbol)
                if result.get("success"):
                    closed_count += 1
                else:
                    errors.append(f"{symbol}: {result.get('error')}")

            logger.info(f"✅ Закрыто позиций: {closed_count}")

            return {"success": True, "closed_count": closed_count, "errors": errors}

        except Exception as e:
            logger.error(f"Ошибка закрытия всех позиций: {e}")
            return {"success": False, "error": str(e)}

    async def get_position_summary(self) -> Dict[str, Any]:
        """Получение сводки по позициям"""
        try:
            total_pnl = 0.0
            position_details = []

            for symbol, position in self.active_positions.items():
                size = float(position.get("pos", "0"))
                entry_price = float(position.get("avgPx", "0"))
                current_price = float(position.get("markPx", "0"))
                side = position.get("posSide", "long")

                # ⚠️ КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: size из API в КОНТРАКТАХ!
                # Нужно получить ctVal для конвертации в монеты перед расчетом PnL
                try:
                    details = await self.client.get_instrument_details(symbol)
                    ct_val = details.get("ctVal", 0.01)  # По умолчанию для BTC/ETH
                    # Реальный размер в монетах
                    size_in_coins = abs(size) * ct_val
                except Exception as e:
                    logger.warning(
                        f"⚠️ Ошибка получения ctVal для {symbol} в get_position_summary: {e}"
                    )
                    # Fallback: предполагаем что size уже в монетах (для совместимости)
                    size_in_coins = abs(size)

                # Расчет PnL (теперь с правильным размером в монетах)
                if side.lower() == "long":
                    pnl = (current_price - entry_price) * size_in_coins
                else:  # short
                    pnl = (entry_price - current_price) * size_in_coins

                total_pnl += pnl

                # Расчет PnL в процентах (от стоимости позиции в USD)
                position_value_usd = size_in_coins * entry_price
                pnl_percent = (
                    (pnl / position_value_usd * 100) if position_value_usd > 0 else 0.0
                )

                position_details.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "size": size,  # В контрактах (для справки)
                        "size_in_coins": size_in_coins,  # В монетах (для расчета)
                        "entry_price": entry_price,
                        "current_price": current_price,
                        "pnl": pnl,
                        "pnl_percent": pnl_percent,
                    }
                )

            return {
                "active_positions_count": len(self.active_positions),
                "total_pnl": total_pnl,
                "positions": position_details,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Ошибка получения сводки по позициям: {e}")
            return {"error": str(e)}

    def get_management_statistics(self) -> Dict[str, Any]:
        """Получение статистики управления позициями"""
        try:
            total = self.management_stats["total_positions"]
            closed = self.management_stats["closed_positions"]

            tp_rate = (
                (self.management_stats["tp_closed"] / closed * 100) if closed > 0 else 0
            )
            sl_rate = (
                (self.management_stats["sl_closed"] / closed * 100) if closed > 0 else 0
            )

            return {
                "total_positions": total,
                "closed_positions": closed,
                "active_positions": len(self.active_positions),
                "tp_closed": self.management_stats["tp_closed"],
                "sl_closed": self.management_stats["sl_closed"],
                "manual_closed": self.management_stats["manual_closed"],
                "tp_rate": tp_rate,
                "sl_rate": sl_rate,
                "total_pnl": self.management_stats["total_pnl"],
                "last_position_time": self.position_history[-1]["close_time"]
                if self.position_history
                else None,
            }

        except Exception as e:
            logger.error(f"Ошибка получения статистики управления: {e}")
            return {"error": str(e)}


# Пример использования
if __name__ == "__main__":
    # Создаем конфигурацию
    config = BotConfig(
        api_key="test_key",
        secret_key="test_secret",
        passphrase="test_passphrase",
        sandbox=True,
    )

    # Создаем клиент и margin calculator
    client = OKXFuturesClient("test_key", "test_secret", "test_passphrase")
    margin_calculator = MarginCalculator()

    # Создаем менеджер позиций
    manager = FuturesPositionManager(config, client, margin_calculator)

    print("FuturesPositionManager готов к работе")
