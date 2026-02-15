import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.strategies.scalping.futures.coordinators.websocket_coordinator import (
    WebSocketCoordinator,
)


def test_safe_float_handles_empty_numeric_fields() -> None:
    assert WebSocketCoordinator._safe_float("", 0.0) == 0.0
    assert WebSocketCoordinator._safe_float("   ", 1.0) == 1.0
    assert WebSocketCoordinator._safe_float(None, 2.0) == 2.0
    assert WebSocketCoordinator._safe_float("12.5", 0.0) == 12.5
