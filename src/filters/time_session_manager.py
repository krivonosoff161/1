"""
Time Session Manager

Управляет торговыми сессиями и временными фильтрами для оптимизации
торговли в периоды высокой ликвидности.

Учитывает основные торговые сессии (Asian, European, American) и их
пересечения для максимизации шансов на успешную сделку.
"""

from datetime import datetime
from datetime import time as dt_time
from typing import Dict, List, Optional, Tuple

from loguru import logger
from pydantic import BaseModel, Field


class TradingSession(BaseModel):
    """Торговая сессия"""

    name: str = Field(description="Название сессии")
    start_hour: int = Field(ge=0, le=23, description="Час начала (UTC)")
    end_hour: int = Field(ge=0, le=23, description="Час окончания (UTC)")
    priority: int = Field(
        default=1, ge=1, le=3, description="Приоритет (1=низкий, 3=высокий)"
    )
    liquidity_multiplier: float = Field(
        default=1.0, ge=0.5, le=2.0, description="Множитель ликвидности"
    )


class SessionOverlap(BaseModel):
    """Пересечение торговых сессий"""

    name: str
    start_hour: int
    end_hour: int
    priority: int = 3  # Пересечения всегда высокий приоритет
    liquidity_multiplier: float = 1.5


class TimeFilterConfig(BaseModel):
    """Конфигурация временного фильтра"""

    enabled: bool = Field(default=True, description="Включить фильтр")

    # Торговые сессии
    trade_asian_session: bool = Field(
        default=True, description="Торговать Азиатскую сессию"
    )
    trade_european_session: bool = Field(
        default=True, description="Торговать Европейскую сессию"
    )
    trade_american_session: bool = Field(
        default=True, description="Торговать Американскую сессию"
    )

    # Приоритет пересечений
    prefer_overlaps: bool = Field(
        default=True, description="Предпочитать пересечения сессий"
    )

    # Низколиквидные часы
    avoid_low_liquidity_hours: bool = Field(
        default=True, description="Избегать низколиквидные часы"
    )
    low_liquidity_hours: List[int] = Field(
        default=[22, 23, 0, 1, 2, 3, 4, 5],
        description="Часы низкой ликвидности (UTC)",
    )

    # Выходные дни
    avoid_weekends: bool = Field(
        default=True, description="Избегать выходных (Saturday night - Sunday)"
    )


class TimeSessionManager:
    """
    Менеджер торговых сессий и временных фильтров.

    Определяет оптимальное время для торговли на основе торговых
    сессий и пересечений между ними.

    Example:
        >>> config = TimeFilterConfig(prefer_overlaps=True)
        >>> manager = TimeSessionManager(config)
        >>> if manager.is_trading_allowed():
        ...     logger.info("Trading time!")
    """

    def __init__(self, config: TimeFilterConfig):
        """
        Инициализация менеджера сессий.

        Args:
            config: Конфигурация временного фильтра
        """
        self.config = config

        # Определяем торговые сессии (UTC)
        self.sessions: Dict[str, TradingSession] = {
            "asian": TradingSession(
                name="Asian",
                start_hour=0,
                end_hour=9,
                priority=1,
                liquidity_multiplier=0.8,
            ),
            "european": TradingSession(
                name="European",
                start_hour=7,
                end_hour=16,
                priority=2,
                liquidity_multiplier=1.2,
            ),
            "american": TradingSession(
                name="American",
                start_hour=13,
                end_hour=22,
                priority=2,
                liquidity_multiplier=1.2,
            ),
        }

        # Определяем пересечения сессий
        self.overlaps: List[SessionOverlap] = [
            SessionOverlap(
                name="Asian-European",
                start_hour=7,
                end_hour=9,
                priority=3,
                liquidity_multiplier=1.3,
            ),
            SessionOverlap(
                name="European-American",
                start_hour=13,
                end_hour=16,
                priority=3,
                liquidity_multiplier=1.5,  # Максимальная ликвидность
            ),
        ]

        logger.info(
            f"Time Session Manager initialized: "
            f"Asian={config.trade_asian_session}, "
            f"European={config.trade_european_session}, "
            f"American={config.trade_american_session}, "
            f"Prefer overlaps={config.prefer_overlaps}"
        )

    def is_trading_allowed(self, current_time: Optional[datetime] = None) -> bool:
        """
        Проверить разрешена ли торговля в текущее время.

        Args:
            current_time: Время для проверки (UTC), None = сейчас

        Returns:
            bool: True если торговля разрешена

        Example:
            >>> if manager.is_trading_allowed():
            ...     # Open position
        """
        if not self.config.enabled:
            return True

        if current_time is None:
            current_time = datetime.utcnow()

        current_hour = current_time.hour
        current_weekday = current_time.weekday()  # 0=Monday, 6=Sunday

        # Проверка выходных
        if self.config.avoid_weekends:
            # Суббота после 22:00 UTC до Воскресенья 22:00 UTC
            if current_weekday == 5 and current_hour >= 22:  # Saturday night
                logger.debug(
                    f"⏰ Trading blocked: Weekend (Saturday {current_hour}:00 UTC)"
                )
                return False
            if current_weekday == 6:  # Sunday
                logger.debug(
                    f"⏰ Trading blocked: Weekend (Sunday {current_hour}:00 UTC)"
                )
                return False

        # Проверка пересечений (если предпочитаем их)
        if self.config.prefer_overlaps:
            for overlap in self.overlaps:
                if self._is_hour_in_range(
                    current_hour, overlap.start_hour, overlap.end_hour
                ):
                    logger.debug(
                        f"✅ Trading allowed: {overlap.name} overlap "
                        f"({current_hour}:00 UTC, liquidity={overlap.liquidity_multiplier}x)"
                    )
                    return True
            # Если prefer_overlaps=True и мы не в пересечении - блокируем
            logger.debug(
                f"⏰ Trading blocked: Outside session overlaps ({current_hour}:00 UTC)"
            )
            return False

        # Проверка активных сессий (если не требуем только пересечения)
        active_sessions = self.get_active_sessions(current_time)
        if active_sessions:
            # Если есть активные сессии - разрешаем торговлю
            session_names = [s.name for s in active_sessions]
            logger.debug(
                f"✅ Trading allowed: Active sessions {session_names} ({current_hour}:00 UTC)"
            )
            return True

        # Проверка низколиквидных часов (только если нет активных сессий)
        if self.config.avoid_low_liquidity_hours:
            if current_hour in self.config.low_liquidity_hours:
                logger.debug(
                    f"⏰ Trading blocked: Low liquidity hour ({current_hour}:00 UTC)"
                )
                return False

        logger.debug(f"⏰ Trading blocked: No active sessions ({current_hour}:00 UTC)")
        return False

    def get_active_sessions(
        self, current_time: Optional[datetime] = None
    ) -> List[TradingSession]:
        """
        Получить активные торговые сессии в текущее время.

        Args:
            current_time: Время для проверки, None = сейчас

        Returns:
            List[TradingSession]: Список активных сессий
        """
        if current_time is None:
            current_time = datetime.utcnow()

        current_hour = current_time.hour
        active = []

        # Проверяем каждую сессию
        if self.config.trade_asian_session:
            session = self.sessions["asian"]
            if self._is_hour_in_range(
                current_hour, session.start_hour, session.end_hour
            ):
                active.append(session)

        if self.config.trade_european_session:
            session = self.sessions["european"]
            if self._is_hour_in_range(
                current_hour, session.start_hour, session.end_hour
            ):
                active.append(session)

        if self.config.trade_american_session:
            session = self.sessions["american"]
            if self._is_hour_in_range(
                current_hour, session.start_hour, session.end_hour
            ):
                active.append(session)

        return active

    def get_current_overlap(
        self, current_time: Optional[datetime] = None
    ) -> Optional[SessionOverlap]:
        """
        Получить текущее пересечение сессий (если есть).

        Args:
            current_time: Время для проверки, None = сейчас

        Returns:
            SessionOverlap или None
        """
        if current_time is None:
            current_time = datetime.utcnow()

        current_hour = current_time.hour

        for overlap in self.overlaps:
            if self._is_hour_in_range(
                current_hour, overlap.start_hour, overlap.end_hour
            ):
                return overlap

        return None

    def get_liquidity_multiplier(
        self, current_time: Optional[datetime] = None
    ) -> float:
        """
        Получить множитель ликвидности для текущего времени.

        Args:
            current_time: Время для проверки, None = сейчас

        Returns:
            float: Множитель ликвидности (0.8 - 1.5)
        """
        if current_time is None:
            current_time = datetime.utcnow()

        # Проверяем пересечения (наивысший приоритет)
        overlap = self.get_current_overlap(current_time)
        if overlap:
            return overlap.liquidity_multiplier

        # Проверяем активные сессии
        active_sessions = self.get_active_sessions(current_time)
        if active_sessions:
            # Берем максимальный множитель из активных сессий
            return max(s.liquidity_multiplier for s in active_sessions)

        # Вне сессий - минимальная ликвидность
        return 0.5

    def get_session_info(self, current_time: Optional[datetime] = None) -> Dict:
        """
        Получить полную информацию о текущем времени торговли.

        Args:
            current_time: Время для проверки, None = сейчас

        Returns:
            Dict с информацией о сессии
        """
        if current_time is None:
            current_time = datetime.utcnow()

        active_sessions = self.get_active_sessions(current_time)
        current_overlap = self.get_current_overlap(current_time)
        liquidity_multiplier = self.get_liquidity_multiplier(current_time)
        trading_allowed = self.is_trading_allowed(current_time)

        return {
            "current_time_utc": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "current_hour": current_time.hour,
            "weekday": current_time.strftime("%A"),
            "trading_allowed": trading_allowed,
            "active_sessions": [s.name for s in active_sessions],
            "current_overlap": current_overlap.name if current_overlap else None,
            "liquidity_multiplier": liquidity_multiplier,
        }

    def _is_hour_in_range(self, hour: int, start_hour: int, end_hour: int) -> bool:
        """
        Проверить находится ли час в диапазоне.

        Args:
            hour: Проверяемый час
            start_hour: Начало диапазона
            end_hour: Конец диапазона

        Returns:
            bool: True если час в диапазоне
        """
        # Обрабатываем случай когда диапазон переходит через полночь
        if start_hour <= end_hour:
            return start_hour <= hour < end_hour
        else:
            # Например, 22:00 - 02:00
            return hour >= start_hour or hour < end_hour

    def get_next_trading_time(
        self, current_time: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Получить время начала следующей торговой сессии.

        Args:
            current_time: Текущее время, None = сейчас

        Returns:
            str: Описание следующей сессии или None
        """
        if current_time is None:
            current_time = datetime.utcnow()

        if self.is_trading_allowed(current_time):
            return "Trading is allowed now"

        current_hour = current_time.hour

        # Ищем ближайшую сессию
        if self.config.prefer_overlaps:
            # Ищем ближайшее пересечение
            for overlap in sorted(self.overlaps, key=lambda x: x.start_hour):
                if overlap.start_hour > current_hour:
                    hours_until = overlap.start_hour - current_hour
                    return f"Next trading: {overlap.name} overlap in {hours_until}h (at {overlap.start_hour}:00 UTC)"
        else:
            # Ищем ближайшую сессию
            next_sessions = []
            if self.config.trade_asian_session:
                next_sessions.append(self.sessions["asian"])
            if self.config.trade_european_session:
                next_sessions.append(self.sessions["european"])
            if self.config.trade_american_session:
                next_sessions.append(self.sessions["american"])

            for session in sorted(next_sessions, key=lambda x: x.start_hour):
                if session.start_hour > current_hour:
                    hours_until = session.start_hour - current_hour
                    return f"Next trading: {session.name} session in {hours_until}h (at {session.start_hour}:00 UTC)"

        return "Next trading: Tomorrow"
