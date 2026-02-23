"""
PositionScalingManager - Управление лестничным добавлением к позициям.

Отвечает за:
- Проверку возможности добавления к существующей позиции
- Расчет размера следующего добавления по лестнице
- Учет leverage существующей позиции
- Валидацию всех лимитов и проверок
"""

import time
from typing import Any, Dict, List, Optional

from loguru import logger

from ..core.position_registry import PositionMetadata, PositionRegistry


class PositionScalingManager:
    """
    Менеджер лестничного добавления к позициям.

    Реализует стратегию постепенного увеличения позиции через несколько добавлений
    с уменьшающимся размером (лестница).
    """

    def __init__(
        self,
        position_registry: PositionRegistry,
        config_manager,
        risk_manager,
        margin_calculator,
        client,
        config,
    ):
        """
        Инициализация PositionScalingManager.

        Args:
            position_registry: Реестр позиций
            config_manager: Менеджер конфигурации
            risk_manager: Менеджер рисков
            margin_calculator: Калькулятор маржи
            client: OKXFuturesClient
            config: Конфигурация бота
        """
        self.position_registry = position_registry
        self.config_manager = config_manager
        self.risk_manager = risk_manager
        self.margin_calculator = margin_calculator
        self.client = client
        self.config = config
        self.scalping_config = getattr(config, "scalping", None)

        logger.info("✅ PositionScalingManager инициализирован")

    def _get_scaling_config(
        self, balance_profile: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получить конфигурацию scaling для профиля баланса.

        Args:
            balance_profile: Профиль баланса (small, medium, large)

        Returns:
            Dict с параметрами scaling
        """
        # Получаем базовую конфигурацию
        scaling_config = getattr(self.scalping_config, "position_scaling", {})
        if not scaling_config:
            # ✅ ИСПРАВЛЕНИЕ (25.12.2025): Оптимизированная лестница для снижения риска
            # Сумма лестницы: 2.0x вместо 3.45x (снижение риска на 42%)
            default_config = {
                "max_additions": 4,  # ✅ ИСПРАВЛЕНИЕ: Снижено с 7 до 4 - меньше добавлений, меньше риск
                "min_interval_seconds": 30,
                "max_loss_for_addition": -5.0,  # ✅ ИСПРАВЛЕНО (КИМИ): -5.0% (было -3.0%) - больше возможностей для добавления
                "ladder": [
                    1.0,
                    0.5,
                    0.3,
                    0.2,
                ],  # ✅ ИСПРАВЛЕНИЕ: Оптимизированная лестница (сумма 2.0x вместо 3.45x)
            }
            logger.info(
                f"ℹ️ [POSITION_SCALING] position_scaling не найден в конфиге, используем агрессивные параметры по умолчанию: {default_config}"
            )
            return default_config

        # Адаптивность по профилю баланса
        if balance_profile:
            by_balance = getattr(scaling_config, "by_balance", {})
            if by_balance and hasattr(by_balance, balance_profile):
                profile_config = getattr(by_balance, balance_profile, {})
                if profile_config:
                    config_dict = {
                        "max_additions": getattr(profile_config, "max_additions", 7),
                        "min_interval_seconds": getattr(
                            profile_config, "min_interval_seconds", 30
                        ),
                        "max_loss_for_addition": getattr(
                            profile_config,
                            "max_loss_for_addition",
                            -5.0,  # ✅ ИСПРАВЛЕНО (КИМИ): -5.0% по умолчанию
                        ),
                        "ladder": getattr(
                            profile_config,
                            "ladder",
                            [
                                1.0,
                                0.5,
                                0.3,
                                0.2,
                            ],  # ✅ ИСПРАВЛЕНИЕ (25.12.2025): Оптимизированная лестница
                        ),
                        "max_additions": min(
                            getattr(profile_config, "max_additions", 4), 4
                        ),  # ✅ ИСПРАВЛЕНИЕ: Ограничение до 4
                    }
                    logger.debug(
                        f"📊 [POSITION_SCALING] Используется конфиг для профиля {balance_profile}: {config_dict}"
                    )
                    return config_dict

        # Базовый конфиг
        config_dict = {
            "max_additions": min(
                getattr(scaling_config, "max_additions", 4), 4
            ),  # ✅ ИСПРАВЛЕНИЕ (25.12.2025): Ограничение до 4
            "min_interval_seconds": getattr(scaling_config, "min_interval_seconds", 30),
            "max_loss_for_addition": getattr(
                scaling_config, "max_loss_for_addition", -3.0
            ),
            "ladder": getattr(
                scaling_config,
                "ladder",
                [
                    1.0,
                    0.5,
                    0.3,
                    0.2,
                ],  # ✅ ИСПРАВЛЕНИЕ (25.12.2025): Оптимизированная лестница
            ),
        }
        return config_dict

    async def can_add_to_position(
        self,
        symbol: str,
        balance: float,
        balance_profile: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Проверить возможность добавления к существующей позиции.

        Args:
            symbol: Торговый символ
            balance: Текущий баланс
            balance_profile: Профиль баланса
            regime: Режим рынка

        Returns:
            Dict с результатом проверки:
                - can_add: bool - можно ли добавлять
                - reason: str - причина если нельзя
                - addition_count: int - текущее количество добавлений
                - last_addition_time: float - время последнего добавления
                - current_pnl_percent: float - текущий PnL% от маржи
        """
        try:
            logger.debug(
                f"🔍 [POSITION_SCALING] Проверка возможности добавления для {symbol}"
            )

            # 1. Проверка наличия позиции
            has_position = await self.position_registry.has_position(symbol)
            if not has_position:
                # ✅ ИСПРАВЛЕНИЕ: Это нормальная ситуация - позиция может быть только что открыта на бирже, но еще не зарегистрирована
                # Не логируем как warning, это debug информация
                logger.debug(
                    f"🔍 [POSITION_SCALING] {symbol}: Позиция не найдена в реестре (это нормально для новой позиции)"
                )
                return {
                    "can_add": False,
                    "reason": "Позиция не найдена в реестре",
                    "addition_count": 0,
                }

            # Получаем метаданные позиции
            metadata = await self.position_registry.get_metadata(symbol)
            if not metadata:
                # ✅ ИСПРАВЛЕНИЕ: Это может быть нормальная ситуация - метаданные могут быть не созданы
                logger.debug(
                    f"🔍 [POSITION_SCALING] {symbol}: Метаданные позиции не найдены (это нормально для новой позиции)"
                )
                return {
                    "can_add": False,
                    "reason": "Метаданные позиции не найдены",
                    "addition_count": 0,
                }

            # Получаем историю добавлений из метаданных
            scaling_history = getattr(metadata, "scaling_history", []) or []
            addition_count = len(scaling_history)

            # 2. Проверка максимального количества добавлений
            scaling_config = self._get_scaling_config(balance_profile)
            max_additions = scaling_config["max_additions"]

            if addition_count >= max_additions:
                return {
                    "can_add": False,
                    "reason": f"Достигнут максимум добавлений ({addition_count}/{max_additions})",
                    "addition_count": addition_count,
                }

            # 3. Проверка интервала между добавлениями
            min_interval_seconds = scaling_config["min_interval_seconds"]
            if scaling_history:
                last_addition_time = scaling_history[-1].get("timestamp", 0)
                time_since_last = time.time() - last_addition_time
                if time_since_last < min_interval_seconds:
                    remaining = min_interval_seconds - time_since_last
                    return {
                        "can_add": False,
                        "reason": f"Интервал между добавлениями не соблюден ({time_since_last:.1f}s < {min_interval_seconds}s, осталось {remaining:.1f}s)",
                        "addition_count": addition_count,
                        "last_addition_time": last_addition_time,
                        "time_since_last": time_since_last,
                    }

            # 4. Получаем текущую позицию для проверки PnL
            position_data = await self.position_registry.get_position(symbol)
            if not position_data:
                return {
                    "can_add": False,
                    "reason": "Данные позиции не найдены",
                    "addition_count": addition_count,
                }

            # Получаем данные с биржи для актуального PnL
            try:
                positions = await self.client.get_positions(symbol)
                current_pnl_percent = None
                for pos in positions:
                    inst_id = pos.get("instId", "").replace("-SWAP", "")
                    if inst_id == symbol:
                        # Получаем unrealizedPnl и margin для расчета PnL%
                        upl_str = str(pos.get("upl", "0")).strip()
                        margin_str = str(pos.get("margin", "0")).strip()
                        try:
                            upl = float(upl_str) if upl_str else 0.0
                            margin = float(margin_str) if margin_str else 0.0
                            if margin > 0:
                                current_pnl_percent = (upl / margin) * 100.0
                        except (ValueError, TypeError):
                            pass
                        # Fallback: расчёт PnL по цене, если upl/margin пустые
                        if current_pnl_percent is None:
                            try:
                                mark_px = float(pos.get("markPx", 0) or 0)
                                avg_px = float(pos.get("avgPx", 0) or 0)
                                pos_side = (pos.get("posSide", "") or "").lower()
                                if mark_px > 0 and avg_px > 0:
                                    if pos_side == "short":
                                        current_pnl_percent = (
                                            (avg_px - mark_px) / avg_px
                                        ) * 100.0
                                    else:
                                        current_pnl_percent = (
                                            (mark_px - avg_px) / avg_px
                                        ) * 100.0
                            except (ValueError, TypeError):
                                pass
                        break
            except Exception as e:
                logger.warning(
                    f"⚠️ [POSITION_SCALING] Ошибка получения PnL с биржи для {symbol}: {e}"
                )
                current_pnl_percent = None

            if current_pnl_percent is None:
                logger.warning(
                    f"⚠️ [POSITION_SCALING] {symbol}: PnL не получен, "
                    f"разрешаем доливку только при отсутствии явного убытка"
                )
                current_pnl_percent = 0.0

            # 5. Проверка убытка
            max_loss_for_addition = scaling_config["max_loss_for_addition"]
            if (
                current_pnl_percent is not None
                and current_pnl_percent < max_loss_for_addition
            ):
                return {
                    "can_add": False,
                    "reason": f"Убыток слишком велик для добавления ({current_pnl_percent:.2f}% < {max_loss_for_addition:.2f}%)",
                    "addition_count": addition_count,
                    "current_pnl_percent": current_pnl_percent,
                }

            # ✅ L3-4 FIX: В trending режиме добавляем только если позиция в прибыли
            # Это предотвращает усреднение убытков в трендовом режиме
            TRENDING_MIN_PROFIT_FOR_ADDITION = (
                1.5  # Минимум 1.5% прибыли для добавления
            )
            if regime and regime.lower() == "trending":
                if (
                    current_pnl_percent is not None
                    and current_pnl_percent < TRENDING_MIN_PROFIT_FOR_ADDITION
                ):
                    return {
                        "can_add": False,
                        "reason": f"В trending режиме добавление только при прибыли >= {TRENDING_MIN_PROFIT_FOR_ADDITION}% (текущая: {current_pnl_percent:.2f}%)",
                        "addition_count": addition_count,
                        "current_pnl_percent": current_pnl_percent,
                    }

            # 6. Проверка доступной маржи (будет проверена в calculate_next_addition_size)
            # Здесь только базовая проверка

            logger.debug(
                f"✅ [POSITION_SCALING] {symbol}: Все проверки пройдены, можно добавлять "
                f"(добавлений: {addition_count}/{max_additions})"
            )

            return {
                "can_add": True,
                "reason": "Все проверки пройдены",
                "addition_count": addition_count,
                "last_addition_time": scaling_history[-1].get("timestamp", 0)
                if scaling_history
                else 0,
                "current_pnl_percent": current_pnl_percent,
            }

        except Exception as e:
            logger.error(
                f"❌ [POSITION_SCALING] Ошибка проверки возможности добавления для {symbol}: {e}",
                exc_info=True,
            )
            return {
                "can_add": False,
                "reason": f"Ошибка проверки: {e}",
                "addition_count": 0,
            }

    async def calculate_next_addition_size(
        self,
        symbol: str,
        base_size_usd: float,
        signal: Dict[str, Any],
        balance: float,
        balance_profile: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> Optional[float]:
        """
        Рассчитать размер следующего добавления к позиции.

        Args:
            symbol: Торговый символ
            base_size_usd: Базовый размер позиции в USD (для расчета лестницы)
            signal: Торговый сигнал
            balance: Текущий баланс
            balance_profile: Профиль баланса
            regime: Режим рынка

        Returns:
            Размер добавления в USD или None если нельзя добавлять
        """
        try:
            logger.debug(
                f"📊 [POSITION_SCALING] Расчет размера добавления для {symbol}, "
                f"базовый размер=${base_size_usd:.2f}"
            )

            # 1. Проверка возможности добавления
            check_result = await self.can_add_to_position(
                symbol, balance, balance_profile, regime
            )
            if not check_result.get("can_add", False):
                # ✅ ИСПРАВЛЕНИЕ: Это нормальная ситуация (например, позиция не найдена, достигнут максимум и т.д.)
                # Логируем как debug, а не warning
                reason = check_result.get("reason", "unknown")
                logger.debug(
                    f"🔍 [POSITION_SCALING] {symbol}: Нельзя добавлять - {reason}"
                )
                return None

            # 2. Получаем конфигурацию scaling
            scaling_config = self._get_scaling_config(balance_profile)
            ladder = scaling_config["ladder"]
            addition_count = check_result["addition_count"]

            # 3. Определяем коэффициент лестницы
            if addition_count >= len(ladder):
                # Если добавлений больше чем элементов лестницы, используем последний
                ladder_coefficient = ladder[-1]
                logger.debug(
                    f"🔧 [POSITION_SCALING] {symbol}: addition_count={addition_count} >= len(ladder)={len(ladder)}, "
                    f"используем последний коэффициент={ladder_coefficient}"
                )
            else:
                ladder_coefficient = ladder[addition_count]
                logger.debug(
                    f"🔧 [POSITION_SCALING] {symbol}: Используем коэффициент лестницы[{addition_count}]={ladder_coefficient}"
                )

            # 4. Рассчитываем размер добавления
            addition_size_usd = base_size_usd * ladder_coefficient

            logger.debug(
                f"📊 [POSITION_SCALING] {symbol}: Размер добавления рассчитан | "
                f"base=${base_size_usd:.2f}, coefficient={ladder_coefficient}, "
                f"addition=${addition_size_usd:.2f}"
            )

            # 5. Получаем leverage существующей позиции (КРИТИЧНО!)
            existing_leverage = await self._get_existing_position_leverage(symbol)
            if existing_leverage:
                logger.info(
                    f"📊 [POSITION_SCALING] {symbol}: Используем leverage существующей позиции={existing_leverage}x "
                    f"(критично для правильного расчета маржи)"
                )
                # Переопределяем leverage в сигнале
                signal["leverage"] = existing_leverage

            # 6. Проверка всех лимитов через risk_manager и margin_calculator
            validation_result = await self._validate_addition_size(
                symbol,
                addition_size_usd,
                existing_leverage,
                balance,
                balance_profile,
                regime,
            )

            if not validation_result.get("valid", False):
                logger.warning(
                    f"⚠️ [POSITION_SCALING] {symbol}: Размер добавления не прошел валидацию - "
                    f"{validation_result.get('reason', 'unknown')}"
                )
                return None

            logger.info(
                f"✅ [POSITION_SCALING] {symbol}: Размер добавления утвержден | "
                f"size=${addition_size_usd:.2f}, leverage={existing_leverage}x, "
                f"ladder_coefficient={ladder_coefficient}"
            )

            return addition_size_usd

        except Exception as e:
            logger.error(
                f"❌ [POSITION_SCALING] Ошибка расчета размера добавления для {symbol}: {e}",
                exc_info=True,
            )
            return None

    async def _get_existing_position_leverage(self, symbol: str) -> Optional[int]:
        """
        Получить leverage существующей позиции.

        Args:
            symbol: Торговый символ

        Returns:
            Leverage позиции или None
        """
        try:
            # Получаем позицию с биржи
            positions = await self.client.get_positions(symbol)
            for pos in positions:
                inst_id = pos.get("instId", "").replace("-SWAP", "")
                if inst_id == symbol:
                    # Пробуем получить leverage из разных полей
                    lever_value = pos.get("lever", "0")
                    if lever_value and lever_value != "0":
                        try:
                            leverage = int(lever_value)
                            if leverage > 0:
                                return leverage
                        except (ValueError, TypeError):
                            pass

                    # Пробуем leverage поле
                    leverage_value = pos.get("leverage", "0")
                    if leverage_value and leverage_value != "0":
                        try:
                            leverage = int(leverage_value)
                            if leverage > 0:
                                return leverage
                        except (ValueError, TypeError):
                            pass
                    break

            logger.warning(
                f"⚠️ [POSITION_SCALING] Не удалось получить leverage позиции {symbol} с биржи"
            )
            return None

        except Exception as e:
            logger.warning(
                f"⚠️ [POSITION_SCALING] Ошибка получения leverage позиции {symbol}: {e}"
            )
            return None

    async def _validate_addition_size(
        self,
        symbol: str,
        addition_size_usd: float,
        leverage: Optional[int],
        balance: float,
        balance_profile: Optional[str],
        regime: Optional[str],
    ) -> Dict[str, Any]:
        """
        Валидация размера добавления по всем лимитам.

        Args:
            symbol: Торговый символ
            addition_size_usd: Размер добавления в USD
            leverage: Leverage позиции
            balance: Текущий баланс
            balance_profile: Профиль баланса
            regime: Режим рынка

        Returns:
            Dict с результатом валидации:
                - valid: bool - валиден ли размер
                - reason: str - причина если невалиден
        """
        try:
            # 1. Проверка что leverage валиден
            if not leverage or leverage <= 0:
                return {
                    "valid": False,
                    "reason": f"Невалидный leverage: {leverage}",
                }

            # 2. Рассчитываем маржу для добавления
            margin_needed = addition_size_usd / leverage

            logger.debug(
                f"🔍 [POSITION_SCALING] {symbol}: Расчет маржи для добавления | "
                f"size=${addition_size_usd:.2f}, leverage={leverage}x, "
                f"margin=${margin_needed:.2f}"
            )

            # 3. Проверка доступной маржи (через margin_calculator)
            if self.margin_calculator:
                try:
                    available_margin = (
                        await self.margin_calculator.get_available_margin(balance)
                    )
                    # Оставляем резерв 20%
                    required_margin_with_reserve = margin_needed * 1.2

                    if required_margin_with_reserve > available_margin:
                        return {
                            "valid": False,
                            "reason": f"Недостаточно маржи: требуется ${required_margin_with_reserve:.2f}, доступно ${available_margin:.2f}",
                        }
                except Exception as e:
                    logger.warning(
                        f"⚠️ [POSITION_SCALING] Ошибка проверки доступной маржи: {e}"
                    )

            # 4. Проверка максимального размера позиции (через risk_manager)
            if self.risk_manager:
                try:
                    # Получаем текущий размер позиции
                    position_data = await self.position_registry.get_position(symbol)
                    if position_data:
                        # Рассчитываем текущий размер в USD (нужно получить ctVal и цену)
                        # Это упрощенная проверка, детальная проверка будет в risk_manager
                        max_margin_per_position = (
                            await self._get_max_margin_per_position(
                                balance, balance_profile, regime
                            )
                        )
                        # Проверяем что маржа добавления не превышает лимит
                        # (упрощенно, детальная проверка нужна с учетом текущей маржи)
                        if margin_needed > max_margin_per_position * 0.5:
                            logger.debug(
                                f"⚠️ [POSITION_SCALING] {symbol}: Маржа добавления ${margin_needed:.2f} "
                                f"больше 50% от max_margin_per_position=${max_margin_per_position:.2f}"
                            )
                except Exception as e:
                    logger.warning(
                        f"⚠️ [POSITION_SCALING] Ошибка проверки максимального размера позиции: {e}"
                    )

            return {"valid": True, "reason": "Все проверки пройдены"}

        except Exception as e:
            logger.error(
                f"❌ [POSITION_SCALING] Ошибка валидации размера добавления для {symbol}: {e}",
                exc_info=True,
            )
            return {
                "valid": False,
                "reason": f"Ошибка валидации: {e}",
            }

    async def _get_max_margin_per_position(
        self,
        balance: float,
        balance_profile: Optional[str],
        regime: Optional[str],
    ) -> float:
        """
        Получить максимальную маржу на позицию.

        Args:
            balance: Текущий баланс
            balance_profile: Профиль баланса
            regime: Режим рынка

        Returns:
            Максимальная маржа на позицию в USD
        """
        try:
            if self.risk_manager and hasattr(
                self.risk_manager, "calculate_max_margin_per_position"
            ):
                return await self.risk_manager.calculate_max_margin_per_position(
                    balance, balance_profile, regime
                )

            # Fallback: простой расчет по балансу
            if balance_profile == "small":
                return balance * 0.15
            elif balance_profile == "medium":
                return balance * 0.20
            else:  # large
                return balance * 0.25

        except Exception as e:
            logger.warning(
                f"⚠️ [POSITION_SCALING] Ошибка получения max_margin_per_position: {e}"
            )
            return balance * 0.20  # Fallback: 20% от баланса

    async def record_scaling_addition(
        self,
        symbol: str,
        addition_size_usd: float,
        leverage: int,
        timestamp: Optional[float] = None,
    ) -> bool:
        """
        Записать факт добавления к позиции в историю.

        Args:
            symbol: Торговый символ
            addition_size_usd: Размер добавления в USD
            leverage: Leverage использованный для добавления
            timestamp: Время добавления (если None, используется текущее)

        Returns:
            True если успешно записано
        """
        try:
            if timestamp is None:
                timestamp = time.time()

            # Получаем метаданные
            metadata = await self.position_registry.get_metadata(symbol)
            if not metadata:
                logger.error(
                    f"❌ [POSITION_SCALING] Не удалось получить метаданные для {symbol}"
                )
                return False

            # Инициализируем scaling_history если нет
            if (
                not hasattr(metadata, "scaling_history")
                or metadata.scaling_history is None
            ):
                metadata.scaling_history = []

            # Добавляем запись
            addition_record = {
                "timestamp": timestamp,
                "size_usd": addition_size_usd,
                "leverage": leverage,
            }

            metadata.scaling_history.append(addition_record)

            # Обновляем метаданные в реестре
            await self.position_registry.update_position(
                symbol, None, {"scaling_history": metadata.scaling_history}
            )

            logger.info(
                f"✅ [POSITION_SCALING] {symbol}: Записано добавление | "
                f"size=${addition_size_usd:.2f}, leverage={leverage}x, "
                f"total_additions={len(metadata.scaling_history)}"
            )

            return True

        except Exception as e:
            logger.error(
                f"❌ [POSITION_SCALING] Ошибка записи добавления для {symbol}: {e}",
                exc_info=True,
            )
            return False
