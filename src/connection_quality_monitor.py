"""
Connection Quality Monitor - автоматическое определение качества соединения и адаптация параметров.

Определяет:
- Использование VPN (по задержкам и ошибкам)
- Качество соединения (отличное/хорошее/плохое)
- Автоматически адаптирует параметры TCPConnector и timeout
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import aiohttp
from loguru import logger


@dataclass
class ConnectionProfile:
    """Профиль параметров соединения."""

    # TCPConnector parameters
    force_close: bool
    limit: int
    ttl_dns_cache: int

    # Timeout parameters
    total_timeout: float
    connect_timeout: float
    sock_read_timeout: float

    # Session parameters
    session_max_age: float

    # Description
    profile_name: str
    description: str


class ConnectionQualityMonitor:
    """
    Мониторинг качества соединения и автоматическая адаптация параметров.

    Периодически проверяет:
    - Задержку (latency) до OKX API
    - Процент неудачных запросов
    - Количество SSL ошибок

    На основе этих метрик определяет:
    - Используется ли VPN
    - Качество соединения (excellent/good/poor)
    - Оптимальный профиль параметров соединения
    """

    # Профили соединения
    PROFILES = {
        "excellent": ConnectionProfile(
            force_close=False,
            limit=10,
            ttl_dns_cache=300,
            total_timeout=10.0,
            connect_timeout=3.0,
            sock_read_timeout=7.0,
            session_max_age=300.0,
            profile_name="excellent",
            description="Отличное соединение (локальная сеть без VPN, <50ms latency)",
        ),
        "good": ConnectionProfile(
            force_close=False,
            limit=10,
            ttl_dns_cache=300,
            total_timeout=15.0,
            connect_timeout=5.0,
            sock_read_timeout=10.0,
            session_max_age=180.0,
            profile_name="good",
            description="Хорошее соединение (50-150ms latency)",
        ),
        "vpn": ConnectionProfile(
            force_close=False,
            limit=10,
            ttl_dns_cache=300,
            total_timeout=60.0,
            connect_timeout=30.0,
            sock_read_timeout=30.0,
            session_max_age=180.0,
            profile_name="vpn",
            description="VPN соединение (>150ms latency, частые разрывы)",
        ),
        "poor": ConnectionProfile(
            force_close=False,
            limit=5,
            ttl_dns_cache=120,
            total_timeout=45.0,
            connect_timeout=20.0,
            sock_read_timeout=25.0,
            session_max_age=180.0,
            profile_name="poor",
            description="Плохое соединение (>200ms latency, много ошибок)",
        ),
    }

    def __init__(
        self,
        check_interval: float = 60.0,  # Проверка каждые 60 секунд
        test_url: str = "https://www.okx.com/api/v5/public/time",
    ):
        """
        Инициализация монитора качества соединения.

        Args:
            check_interval: Интервал проверки качества (секунды)
            test_url: URL для тестирования соединения
        """
        self.check_interval = check_interval
        self.test_url = test_url

        # Метрики
        self._latency_samples = []  # Последние 10 замеров задержки
        self._error_count = 0  # Счетчик ошибок
        self._request_count = 0  # Счетчик запросов
        self._ssl_error_count = 0  # Счетчик SSL ошибок

        # Текущий профиль
        self._current_profile: Optional[ConnectionProfile] = None
        self._profile_change_time: Optional[float] = None

        # Защита от частых переключений
        self._min_profile_duration = 300.0  # Минимум 5 минут в одном профиле

        # Флаг работы
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        """Запуск мониторинга."""
        if self._running:
            logger.warning("ConnectionQualityMonitor уже запущен")
            return

        self._running = True
        logger.info(
            "🌐 ConnectionQualityMonitor: Запуск мониторинга качества соединения"
        )

        # Первоначальная проверка
        await self._check_connection_quality()

        # Запуск фоновой задачи
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Остановка мониторинга."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("🌐 ConnectionQualityMonitor: Мониторинг остановлен")

    async def _monitor_loop(self):
        """Главный цикл мониторинга."""
        try:
            while self._running:
                await asyncio.sleep(self.check_interval)
                await self._check_connection_quality()
        except asyncio.CancelledError:
            logger.debug("ConnectionQualityMonitor: Мониторинг прерван")
        except Exception as e:
            logger.error(f"ConnectionQualityMonitor: Ошибка в цикле мониторинга: {e}")

    async def _check_connection_quality(self):
        """Проверка качества соединения и обновление профиля."""
        try:
            # Измерение задержки
            latency = await self._measure_latency()

            if latency is not None:
                # Сохраняем последние 10 замеров
                self._latency_samples.append(latency)
                if len(self._latency_samples) > 10:
                    self._latency_samples.pop(0)

                # Вычисляем среднюю задержку
                avg_latency = sum(self._latency_samples) / len(self._latency_samples)

                # Вычисляем процент ошибок
                error_rate = (
                    self._error_count / self._request_count * 100
                    if self._request_count > 0
                    else 0
                )

                # Определяем оптимальный профиль
                new_profile = self._determine_profile(avg_latency, error_rate)

                # Применяем новый профиль (если нужно)
                if new_profile != self._current_profile:
                    await self._apply_profile(new_profile)

                # Логирование метрик
                logger.info(
                    f"🌐 Connection: latency={avg_latency:.0f}ms, "
                    f"errors={error_rate:.1f}%, "
                    f"ssl_errors={self._ssl_error_count}, "
                    f"profile={new_profile.profile_name}"
                )

        except Exception as e:
            logger.error(f"ConnectionQualityMonitor: Ошибка проверки качества: {e}")

    async def _measure_latency(self) -> Optional[float]:
        """
        Измерение задержки до OKX API.

        Returns:
            Задержка в миллисекундах или None при ошибке
        """
        try:
            start_time = time.time()

            timeout = aiohttp.ClientTimeout(total=10.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.test_url) as response:
                    await response.text()

            end_time = time.time()
            latency_ms = (end_time - start_time) * 1000

            self._request_count += 1
            return latency_ms

        except aiohttp.ClientSSLError as e:
            self._error_count += 1
            self._ssl_error_count += 1
            self._request_count += 1
            logger.debug(f"SSL error при измерении latency: {e}")
            return None

        except Exception as e:
            self._error_count += 1
            self._request_count += 1
            logger.debug(f"Ошибка измерения latency: {e}")
            return None

    def _determine_profile(
        self, avg_latency: float, error_rate: float
    ) -> ConnectionProfile:
        """
        Определение оптимального профиля соединения.

        Args:
            avg_latency: Средняя задержка (мс)
            error_rate: Процент ошибок (%)

        Returns:
            Оптимальный профиль соединения
        """
        # Плохое соединение: много ошибок или очень высокая задержка
        if error_rate > 20 or avg_latency > 300:
            return self.PROFILES["poor"]

        # VPN соединение: высокая задержка + SSL ошибки
        if avg_latency > 150 and self._ssl_error_count > 3:
            return self.PROFILES["vpn"]

        # Хорошее соединение: средняя задержка
        if 50 < avg_latency <= 150:
            return self.PROFILES["good"]

        # Отличное соединение: низкая задержка
        if avg_latency <= 50:
            return self.PROFILES["excellent"]

        # Fallback на good
        return self.PROFILES["good"]

    async def _apply_profile(self, new_profile: ConnectionProfile):
        """
        Применение нового профиля соединения.

        Args:
            new_profile: Новый профиль для применения
        """
        # Защита от частых переключений
        now = time.time()
        if self._profile_change_time:
            time_since_change = now - self._profile_change_time
            if time_since_change < self._min_profile_duration:
                logger.debug(
                    f"ConnectionQualityMonitor: Пропускаем смену профиля "
                    f"(прошло {time_since_change:.0f}s < {self._min_profile_duration:.0f}s)"
                )
                return

        # Логирование смены профиля
        old_profile_name = (
            self._current_profile.profile_name if self._current_profile else "none"
        )
        logger.warning(
            f"🔄 ConnectionQualityMonitor: Смена профиля соединения:\n"
            f"   Было: {old_profile_name}\n"
            f"   Стало: {new_profile.profile_name}\n"
            f"   Описание: {new_profile.description}\n"
            f"   Параметры:\n"
            f"     - force_close: {new_profile.force_close}\n"
            f"     - total_timeout: {new_profile.total_timeout}s\n"
            f"     - connect_timeout: {new_profile.connect_timeout}s\n"
            f"     - session_max_age: {new_profile.session_max_age}s"
        )

        self._current_profile = new_profile
        self._profile_change_time = now

        # Сброс счетчиков ошибок для нового профиля
        self._error_count = 0
        self._ssl_error_count = 0
        self._request_count = 0

    def get_current_profile(self) -> Optional[ConnectionProfile]:
        """Получение текущего профиля соединения."""
        return self._current_profile

    def get_connector_params(self) -> dict:
        """
        Получение параметров TCPConnector для текущего профиля.

        Returns:
            Словарь параметров для TCPConnector
        """
        profile = self._current_profile or self.PROFILES["good"]
        return {
            "force_close": profile.force_close,
            "limit": profile.limit,
            "ttl_dns_cache": profile.ttl_dns_cache,
            "enable_cleanup_closed": True,
        }

    def get_timeout_params(self) -> aiohttp.ClientTimeout:
        """
        Получение параметров timeout для текущего профиля.

        Returns:
            ClientTimeout объект
        """
        profile = self._current_profile or self.PROFILES["good"]
        return aiohttp.ClientTimeout(
            total=profile.total_timeout,
            connect=profile.connect_timeout,
            sock_read=profile.sock_read_timeout,
        )

    def get_session_max_age(self) -> float:
        """
        Получение максимального времени жизни сессии для текущего профиля.

        Returns:
            Время жизни сессии (секунды)
        """
        profile = self._current_profile or self.PROFILES["good"]
        return profile.session_max_age

    def record_error(self, is_ssl_error: bool = False):
        """
        Запись ошибки для статистики.

        Args:
            is_ssl_error: True если это SSL ошибка
        """
        self._error_count += 1
        if is_ssl_error:
            self._ssl_error_count += 1
