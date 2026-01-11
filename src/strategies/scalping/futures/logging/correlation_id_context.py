"""
CorrelationIdContext - Управление correlation ID для трейсинга.

Генерирует и передает уникальный correlation ID через все логи для упрощения отладки.
"""

import contextvars
import uuid
from typing import Optional

# Context variable для хранения correlation ID в asyncio контексте
_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=None
)


class CorrelationIdContext:
    """
    Менеджер для управления correlation ID в логах.
    
    Позволяет:
    - Генерировать уникальные correlation IDs
    - Сохранять их в asyncio контексте
    - Получать текущий correlation ID в любом месте кода
    """

    @staticmethod
    def generate_id(prefix: str = "req") -> str:
        """
        Генерирует новый уникальный correlation ID.
        
        Args:
            prefix: Префикс для ID (например, 'req' для request, 'trade' для trade)
            
        Returns:
            Уникальный ID вида 'prefix_uuid'
        """
        unique_id = str(uuid.uuid4())[:8]  # Первые 8 символов UUID
        return f"{prefix}_{unique_id}"

    @staticmethod
    def set_correlation_id(correlation_id: str) -> None:
        """
        Устанавливает correlation ID в asyncio контексте.
        
        Args:
            correlation_id: ID для установки
        """
        _correlation_id_var.set(correlation_id)

    @staticmethod
    def get_correlation_id() -> Optional[str]:
        """
        Получает текущий correlation ID из контекста.
        
        Returns:
            Текущий correlation ID или None
        """
        return _correlation_id_var.get()

    @staticmethod
    def clear_correlation_id() -> None:
        """Очищает correlation ID из контекста"""
        _correlation_id_var.set(None)

    @staticmethod
    def with_correlation_id(correlation_id: str):
        """
        Context manager для временной установки correlation ID.
        
        Args:
            correlation_id: ID для установки в контексте
            
        Usage:
            with CorrelationIdContext.with_correlation_id("trade_abc123"):
                # Все логи будут содержать это correlation_id
                logger.info("Trade executed")
        """
        class CorrelationIdContextManager:
            def __enter__(self):
                self.token = _correlation_id_var.set(correlation_id)
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                _correlation_id_var.reset(self.token)
                return False

        return CorrelationIdContextManager()
