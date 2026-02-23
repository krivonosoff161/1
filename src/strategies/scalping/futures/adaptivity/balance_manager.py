"""
Adaptive Balance Manager для OKX Trading Bot

Управляет адаптивными параметрами торговли в зависимости от текущего баланса аккаунта.
Автоматически переключает профили и применяет соответствующие параметры.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

# 🔴 BUG #33 FIX: Bridge logging to loguru
from loguru import logger as loguru_logger


class InterceptHandler(logging.Handler):
    """Перенаправляет стандартные логи logging в loguru"""

    def emit(self, record):
        # Получаем имя логгера из стандартного logging
        level = record.levelno

        # Перенаправляем в loguru
        loguru_logger.log(level, record.getMessage())


logger = loguru_logger

# Redirect stdlib logging to loguru
logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG)


class BalanceProfile(Enum):
    """Профили баланса аккаунта"""

    SMALL = "small"  # до $1000
    MEDIUM = "medium"  # $1000 - $2500
    LARGE = "large"  # от $2500


@dataclass
class BalanceProfileConfig:
    """Конфигурация профиля баланса"""

    # Пороговые значения
    threshold: float

    # Размеры позиций
    base_position_size: float
    min_position_size: float
    max_position_size: float

    # Максимальные позиции
    max_open_positions: int
    max_position_percent: float  # % от баланса на одну позицию

    # Boost множители для разных режимов рынка
    trending_boost: Dict[str, float]  # boost для trending режима
    ranging_boost: Dict[str, float]  # boost для ranging режима
    choppy_boost: Dict[str, float]  # boost для choppy режима

    # Адаптивные параметры
    tp_multiplier_boost: float = 1.0
    sl_multiplier_boost: float = 1.0
    ph_threshold_boost: float = 1.0
    score_threshold_boost: float = 1.0
    max_trades_boost: float = 1.0


@dataclass
class BalanceUpdateEvent:
    """Событие обновления баланса"""

    event_type: str  # "position_opened", "position_closed", "manual_update"
    symbol: Optional[str] = None
    side: Optional[str] = None
    amount: Optional[float] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class AdaptiveBalanceManager:
    """
    Менеджер адаптивного баланса.

    Автоматически определяет профиль баланса и применяет соответствующие
    параметры торговли для оптимизации прибыли и управления рисками.
    """

    def __init__(self, profiles: Dict[str, BalanceProfileConfig]):
        self.profiles = profiles
        self.current_profile: Optional[BalanceProfile] = None
        self.current_balance: float = 0.0
        self.last_balance_update: datetime = datetime.utcnow()

        # Статистика
        self.profile_switches: List[Dict[str, Any]] = []
        self.balance_history: List[Dict[str, Any]] = []

        # События для обновления баланса
        self.balance_events: List[BalanceUpdateEvent] = []

        logger.info("💰 Adaptive Balance Manager initialized")
        self._log_profiles()

    def _log_profiles(self):
        """Логирование профилей баланса"""
        logger.info("📊 Balance Profiles:")
        for name, profile in self.profiles.items():
            logger.info(
                f"  {name.upper()}: ${profile.threshold:,.0f}+ | "
                f"Positions: {profile.max_open_positions} | "
                f"Max Size: ${profile.max_position_size:,.0f}"
            )

    def update_balance(
        self, new_balance: float, event: Optional[BalanceUpdateEvent] = None
    ) -> bool:
        """
        Обновляет текущий баланс и переключает профиль при необходимости.

        Args:
            new_balance: Новый баланс аккаунта
            event: Событие, вызвавшее обновление

        Returns:
            True если профиль изменился, False если остался прежним
        """
        old_profile = self.current_profile
        old_balance = self.current_balance

        self.current_balance = new_balance
        self.last_balance_update = datetime.utcnow()

        # Определяем новый профиль
        new_profile = self._determine_profile(new_balance)

        # Записываем в историю
        self.balance_history.append(
            {
                "timestamp": self.last_balance_update,
                "balance": new_balance,
                "profile": new_profile.value if new_profile else None,
                "event": event.event_type if event else "manual_update",
            }
        )

        # Ограничиваем историю
        if len(self.balance_history) > 1000:
            self.balance_history = self.balance_history[-500:]

        # Проверяем изменение профиля
        if new_profile != old_profile:
            self._switch_profile(old_profile, new_profile, old_balance, new_balance)
            return True

        return False

    def _determine_profile(self, balance: float) -> BalanceProfile:
        """
        ✅ L5-2 FIX: Определяет профиль на основе баланса с гистерезисом ±5%.

        Гистерезис предотвращает частые переключения при колебаниях баланса
        около границ (например, $950-$1050 для small/medium).

        Пороги перехода:
        - small → medium: $1000 (без гистерезиса, начальный переход)
        - medium → small: $950 (с гистерезисом -5%)
        - medium → large: $2500 (без гистерезиса, начальный переход)
        - large → medium: $2375 (с гистерезисом -5%)
        """
        HYSTERESIS_PCT = 0.05  # 5% гистерезис

        # Получаем пороги
        small_threshold = self.profiles["small"].threshold  # 1000
        medium_threshold = self.profiles["medium"].threshold  # 2500
        large_threshold = self.profiles["large"].threshold  # 3500

        # Текущий профиль (для гистерезиса)
        current = self.current_profile

        # Если профиль ещё не установлен - используем жёсткие пороги
        if current is None:
            if balance >= large_threshold:
                return BalanceProfile.LARGE
            elif balance >= medium_threshold:
                return BalanceProfile.MEDIUM
            else:
                return BalanceProfile.SMALL

        # Гистерезис: учитываем текущий профиль при определении нового
        if current == BalanceProfile.SMALL:
            # Из small: переходим в medium только при достижении medium_threshold
            if balance >= medium_threshold:
                return BalanceProfile.MEDIUM
            return BalanceProfile.SMALL

        elif current == BalanceProfile.MEDIUM:
            # Из medium:
            # - в large при достижении large_threshold
            # - в small только если упали ниже medium_threshold с гистерезисом
            if balance >= large_threshold:
                return BalanceProfile.LARGE
            elif balance < medium_threshold * (
                1 - HYSTERESIS_PCT
            ):  # 2500 * 0.95 = 2375
                return BalanceProfile.SMALL
            return BalanceProfile.MEDIUM

        elif current == BalanceProfile.LARGE:
            # Из large: переходим в medium только если упали ниже large_threshold с гистерезисом
            if balance < large_threshold * (1 - HYSTERESIS_PCT):  # 3500 * 0.95 = 3325
                return BalanceProfile.MEDIUM
            return BalanceProfile.LARGE

        # Fallback (не должно произойти)
        return BalanceProfile.SMALL

    def _switch_profile(
        self,
        old_profile: Optional[BalanceProfile],
        new_profile: BalanceProfile,
        old_balance: float,
        new_balance: float,
    ):
        """Переключает профиль баланса"""
        self.current_profile = new_profile

        # Записываем переключение
        switch_info = {
            "timestamp": self.last_balance_update,
            "old_profile": old_profile.value if old_profile else None,
            "new_profile": new_profile.value,
            "old_balance": old_balance,
            "new_balance": new_balance,
            "balance_change": new_balance - old_balance,
        }
        self.profile_switches.append(switch_info)

        # Ограничиваем историю переключений
        if len(self.profile_switches) > 100:
            self.profile_switches = self.profile_switches[-50:]

        logger.info(
            f"🔄 Profile switched: {old_profile.value if old_profile else 'None'} → {new_profile.value}"
        )
        logger.info(
            f"💰 Balance: ${old_balance:,.2f} → ${new_balance:,.2f} (${new_balance - old_balance:+,.2f})"
        )

    def get_current_profile_config(self) -> Optional[BalanceProfileConfig]:
        """Получает конфигурацию текущего профиля"""
        if self.current_profile is None:
            return None
        return self.profiles[self.current_profile.value]

    def apply_to_regime_params(
        self, regime_params: Dict[str, Any], regime: str
    ) -> Dict[str, Any]:
        """
        Применяет адаптивные параметры к параметрам режима рынка.

        Args:
            regime_params: Параметры режима рынка
            regime: Название режима ("trending", "ranging", "choppy")

        Returns:
            Обновленные параметры с применением boost множителей
        """
        if self.current_profile is None:
            return regime_params

        profile_config = self.get_current_profile_config()
        if profile_config is None:
            return regime_params

        # Создаем копию параметров
        adapted_params = regime_params.copy()

        # Получаем boost для текущего режима
        boost_config = self._get_boost_config(profile_config, regime)

        # Применяем boost к параметрам
        adapted_params = self._apply_boost_multipliers(adapted_params, boost_config)

        # Логируем применение
        logger.debug(
            f"🎯 Applied {self.current_profile.value.upper()} profile to {regime} regime"
        )
        logger.debug(f"📈 Boost multipliers: {boost_config}")

        return adapted_params

    def _get_boost_config(
        self, profile_config: BalanceProfileConfig, regime: str
    ) -> Dict[str, float]:
        """Получает конфигурацию boost для режима"""
        if regime == "trending":
            return profile_config.trending_boost
        elif regime == "ranging":
            return profile_config.ranging_boost
        elif regime == "choppy":
            return profile_config.choppy_boost
        else:
            return {}

    def _apply_boost_multipliers(
        self, params: Dict[str, Any], boost_config: Dict[str, float]
    ) -> Dict[str, Any]:
        """Применяет boost множители к параметрам"""
        adapted = params.copy()

        # Применяем общие boost множители
        if "tp_multiplier" in adapted and "tp_multiplier" in boost_config:
            adapted["tp_multiplier"] *= boost_config["tp_multiplier"]

        if "sl_multiplier" in adapted and "sl_multiplier" in boost_config:
            adapted["sl_multiplier"] *= boost_config["sl_multiplier"]

        if "ph_threshold" in adapted and "ph_threshold" in boost_config:
            adapted["ph_threshold"] *= boost_config["ph_threshold"]

        if "score_threshold" in adapted and "score_threshold" in boost_config:
            adapted["score_threshold"] *= boost_config["score_threshold"]

        if "max_trades_per_hour" in adapted and "max_trades" in boost_config:
            adapted["max_trades_per_hour"] = int(
                adapted["max_trades_per_hour"] * boost_config["max_trades"]
            )

        return adapted

    def get_position_sizing_params(self) -> Dict[str, Any]:
        """Получает параметры размеров позиций для текущего профиля"""
        if self.current_profile is None:
            return {}

        profile_config = self.get_current_profile_config()
        if profile_config is None:
            return {}

        return {
            "base_position_size": profile_config.base_position_size,
            "min_position_size": profile_config.min_position_size,
            "max_position_size": profile_config.max_position_size,
            "max_open_positions": profile_config.max_open_positions,
            "max_position_percent": profile_config.max_position_percent,
        }

    def check_and_update_balance(self, event: str, **kwargs) -> bool:
        """
        Проверяет и обновляет баланс на основе события.

        Args:
            event: Тип события ("position_opened", "position_closed", "manual_update")
            **kwargs: Дополнительные параметры события

        Returns:
            True если баланс был обновлен
        """
        # Создаем событие
        balance_event = BalanceUpdateEvent(
            event_type=event,
            symbol=kwargs.get("symbol"),
            side=kwargs.get("side"),
            amount=kwargs.get("amount"),
        )

        self.balance_events.append(balance_event)

        # Ограничиваем историю событий
        if len(self.balance_events) > 1000:
            self.balance_events = self.balance_events[-500:]

        # В реальной реализации здесь был бы запрос к API для получения актуального баланса
        # Пока что просто логируем событие
        logger.debug(
            f"📊 Balance event: {event} | Symbol: {kwargs.get('symbol')} | Amount: {kwargs.get('amount')}"
        )

        return True

    def get_balance_stats(self) -> Dict[str, Any]:
        """Получает статистику баланса"""
        return {
            "current_balance": self.current_balance,
            "current_profile": self.current_profile.value
            if self.current_profile
            else None,
            "last_update": self.last_balance_update.isoformat(),
            "profile_switches_count": len(self.profile_switches),
            "balance_history_count": len(self.balance_history),
            "recent_switches": self.profile_switches[-5:]
            if self.profile_switches
            else [],
            "recent_events": self.balance_events[-10:] if self.balance_events else [],
        }

    def get_profile_recommendations(self) -> Dict[str, Any]:
        """Получает рекомендации по профилю"""
        if self.current_profile is None:
            return {"message": "No profile determined yet"}

        profile_config = self.get_current_profile_config()
        if profile_config is None:
            return {"message": "Profile config not found"}

        recommendations = {
            "current_profile": self.current_profile.value,
            "balance": self.current_balance,
            "recommendations": [],
        }

        # Рекомендации по размеру позиций
        if self.current_balance < profile_config.max_position_size * 2:
            recommendations["recommendations"].append(
                f"Consider reducing position size to ${profile_config.min_position_size:,.0f} "
                f"for better risk management"
            )

        # Рекомендации по количеству позиций
        if (
            self.current_balance
            < profile_config.max_position_size * profile_config.max_open_positions
        ):
            recommendations["recommendations"].append(
                f"Limit open positions to {max(1, profile_config.max_open_positions // 2)} "
                f"until balance increases"
            )

        return recommendations


def create_default_profiles() -> Dict[str, BalanceProfileConfig]:
    """Создает профили баланса по умолчанию"""
    return {
        "small": BalanceProfileConfig(
            threshold=1000.0,
            base_position_size=50.0,
            min_position_size=25.0,
            max_position_size=100.0,
            max_open_positions=2,
            max_position_percent=10.0,
            trending_boost={
                "tp_multiplier": 1.2,
                "sl_multiplier": 0.9,
                "ph_threshold": 1.1,
                "score_threshold": 0.9,
                "max_trades": 1.1,
            },
            ranging_boost={
                "tp_multiplier": 1.0,
                "sl_multiplier": 1.0,
                "ph_threshold": 1.0,
                "score_threshold": 1.0,
                "max_trades": 1.0,
            },
            choppy_boost={
                "tp_multiplier": 0.8,
                "sl_multiplier": 1.2,
                "ph_threshold": 0.9,
                "score_threshold": 1.1,
                "max_trades": 0.8,
            },
        ),
        "medium": BalanceProfileConfig(
            threshold=2500.0,
            base_position_size=100.0,
            min_position_size=50.0,
            max_position_size=200.0,
            max_open_positions=3,
            max_position_percent=8.0,
            trending_boost={
                "tp_multiplier": 1.3,
                "sl_multiplier": 0.8,
                "ph_threshold": 1.2,
                "score_threshold": 0.8,
                "max_trades": 1.2,
            },
            ranging_boost={
                "tp_multiplier": 1.1,
                "sl_multiplier": 0.9,
                "ph_threshold": 1.1,
                "score_threshold": 0.9,
                "max_trades": 1.1,
            },
            choppy_boost={
                "tp_multiplier": 0.9,
                "sl_multiplier": 1.1,
                "ph_threshold": 1.0,
                "score_threshold": 1.0,
                "max_trades": 0.9,
            },
        ),
        "large": BalanceProfileConfig(
            threshold=3500.0,
            base_position_size=200.0,
            min_position_size=100.0,
            max_position_size=500.0,
            max_open_positions=5,
            max_position_percent=6.0,
            trending_boost={
                "tp_multiplier": 1.5,
                "sl_multiplier": 0.7,
                "ph_threshold": 1.3,
                "score_threshold": 0.7,
                "max_trades": 1.5,
            },
            ranging_boost={
                "tp_multiplier": 1.2,
                "sl_multiplier": 0.8,
                "ph_threshold": 1.2,
                "score_threshold": 0.8,
                "max_trades": 1.2,
            },
            choppy_boost={
                "tp_multiplier": 1.0,
                "sl_multiplier": 1.0,
                "ph_threshold": 1.1,
                "score_threshold": 0.9,
                "max_trades": 1.0,
            },
        ),
    }
