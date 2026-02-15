import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.strategies.scalping.futures.metrics.slo_monitor import SLOMonitor


def test_slo_monitor_rates_and_alerts() -> None:
    monitor = SLOMonitor(
        config={
            "slo_monitor": {
                "enabled": True,
                "window_sec": 60,
                "alert_cooldown_sec": 1,
                "thresholds": {
                    "ws_stale_signal_fallback_per_hour": 1,
                    "stale_ratio_max": 0.1,
                },
            }
        }
    )

    monitor.record_event("ws_stale_signal_fallback")
    monitor.record_decision_snapshot(rest_fallback=True)
    monitor.record_decision_snapshot(rest_fallback=False)

    snapshot = monitor.get_snapshot()
    assert snapshot["ws_stale_signal_fallback_per_hour"] > 1
    assert snapshot["stale_ratio"] == 0.5

    alerts = monitor.evaluate_alerts()
    metrics = {alert["metric"] for alert in alerts}
    assert "ws_stale_signal_fallback_per_hour" in metrics
    assert "stale_ratio_max" in metrics


def test_slo_monitor_alert_cooldown() -> None:
    monitor = SLOMonitor(
        config={
            "slo_monitor": {
                "enabled": True,
                "window_sec": 60,
                "alert_cooldown_sec": 60,
                "thresholds": {"ws_stale_watchdog_per_hour": 1},
            }
        }
    )

    monitor.record_event("ws_stale_watchdog")
    first = monitor.evaluate_alerts()
    second = monitor.evaluate_alerts()

    assert len(first) == 1
    assert len(second) == 0

    # Manually move cooldown window for deterministic check.
    monitor._last_alert_ts["ws_stale_watchdog_per_hour"] = time.time() - 61
    third = monitor.evaluate_alerts()
    assert len(third) == 1
