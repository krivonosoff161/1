"""
ExitDecisionLogger - Логирование решений ExitAnalyzer.

Сохраняет все решения ExitAnalyzer в JSON файлы для последующего анализа.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger


class ExitDecisionLogger:
    """
    Логирование решений ExitAnalyzer.

    Сохраняет решения в JSON файлы в папке logs/futures/debug/exit_decisions/
    """

    def __init__(self, log_dir: str = "logs/futures/debug/exit_decisions"):
        """
        Инициализация ExitDecisionLogger.

        Args:
            log_dir: Директория для сохранения логов
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"✅ ExitDecisionLogger инициализирован (log_dir={log_dir})")

    def log_decision(
        self,
        symbol: str,
        decision: Dict[str, Any],
        position_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Логировать решение ExitAnalyzer.

        Args:
            symbol: Торговый символ
            decision: Решение ExitAnalyzer
            position_data: Данные позиции (опционально)
        """
        try:
            # Создаем имя файла: {symbol}_{timestamp}.json
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]  # Миллисекунды
            filename = f"{symbol}_{timestamp}.json"
            filepath = self.log_dir / filename

            # Формируем структурированный лог
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "decision": decision.get("action"),  # extend_tp, close, protect, etc.
                "reason": decision.get("reason"),
                "pnl_pct": decision.get("pnl_pct"),
                "regime": decision.get("regime"),
                "trend_strength": decision.get("trend_strength"),
                "reversal_confidence": decision.get("reversal_confidence"),
                "metadata": {
                    "duration_minutes": decision.get("duration_minutes"),
                    "entry_price": decision.get("entry_price"),
                    "current_price": decision.get("current_price"),
                    "position_side": decision.get("position_side"),
                },
            }

            # Добавляем данные позиции, если предоставлены
            if position_data:
                log_entry["position_data"] = position_data

            # Добавляем все дополнительные поля из decision
            for key, value in decision.items():
                if key not in log_entry and key not in log_entry.get("metadata", {}):
                    log_entry[key] = value

            # Сохраняем в JSON файл
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(log_entry, f, indent=2, ensure_ascii=False)

            logger.debug(
                f"✅ ExitDecisionLogger: Решение для {symbol} сохранено: {filepath}"
            )

        except Exception as e:
            logger.error(
                f"❌ ExitDecisionLogger: Ошибка логирования решения для {symbol}: {e}",
                exc_info=True,
            )

