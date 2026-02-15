from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from loguru import logger


class SLOMonitor:
    """Tracks runtime SLO counters and emits threshold alerts."""

    DEFAULT_WINDOW_SEC = 3600.0
    DEFAULT_ALERT_COOLDOWN_SEC = 300.0
    DEFAULT_THRESHOLDS = {
        "ws_stale_signal_fallback_per_hour": 5.0,
        "ws_stale_watchdog_per_hour": 2.0,
        "close_pipeline_errors_per_hour": 0.0,
        "pnl_mismatch_per_hour": 10.0,
        "ws_parse_errors_per_hour": 10.0,
        "same_side_reentry_count_per_hour": 20.0,
        "stale_ratio_max": 0.15,
    }
    EVENT_TO_THRESHOLD = {
        "ws_stale_signal_fallback": "ws_stale_signal_fallback_per_hour",
        "ws_stale_watchdog": "ws_stale_watchdog_per_hour",
        "close_pipeline_errors": "close_pipeline_errors_per_hour",
        "pnl_mismatch": "pnl_mismatch_per_hour",
        "ws_parse_errors": "ws_parse_errors_per_hour",
        "same_side_reentry_count": "same_side_reentry_count_per_hour",
    }

    def __init__(
        self, config: Optional[Any] = None, alert_manager: Optional[Any] = None
    ):
        self.enabled = True
        self.window_sec = self.DEFAULT_WINDOW_SEC
        self.alert_cooldown_sec = self.DEFAULT_ALERT_COOLDOWN_SEC
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        self.alert_manager = alert_manager

        self._event_ts: Dict[str, Deque[float]] = defaultdict(deque)
        self._decision_snapshot_events: Deque[Tuple[float, bool]] = deque()
        self._last_alert_ts: Dict[str, float] = {}

        self._load_config(config)

    @staticmethod
    def _cfg_get(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _load_config(self, config: Optional[Any]) -> None:
        slo_cfg = self._cfg_get(config, "slo_monitor", {})
        if not isinstance(slo_cfg, dict):
            slo_cfg = {}

        self.enabled = bool(slo_cfg.get("enabled", self.enabled))
        try:
            self.window_sec = max(
                60.0, float(slo_cfg.get("window_sec", self.window_sec))
            )
        except (TypeError, ValueError):
            self.window_sec = self.DEFAULT_WINDOW_SEC
        try:
            self.alert_cooldown_sec = max(
                10.0, float(slo_cfg.get("alert_cooldown_sec", self.alert_cooldown_sec))
            )
        except (TypeError, ValueError):
            self.alert_cooldown_sec = self.DEFAULT_ALERT_COOLDOWN_SEC

        thresholds = slo_cfg.get("thresholds", {})
        if isinstance(thresholds, dict):
            for key, value in thresholds.items():
                try:
                    self.thresholds[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue

    def _prune(self, now_ts: Optional[float] = None) -> None:
        now = now_ts or time.time()
        min_ts = now - self.window_sec
        for queue in self._event_ts.values():
            while queue and queue[0] < min_ts:
                queue.popleft()
        while (
            self._decision_snapshot_events
            and self._decision_snapshot_events[0][0] < min_ts
        ):
            self._decision_snapshot_events.popleft()

    def record_event(self, name: str, count: int = 1) -> None:
        if not self.enabled:
            return
        event_name = str(name or "").strip()
        if not event_name:
            return
        if count <= 0:
            return
        now = time.time()
        queue = self._event_ts[event_name]
        for _ in range(int(count)):
            queue.append(now)
        self._prune(now)

    def record_decision_snapshot(self, rest_fallback: bool) -> None:
        if not self.enabled:
            return
        now = time.time()
        self._decision_snapshot_events.append((now, bool(rest_fallback)))
        self._prune(now)

    def _get_event_count(self, name: str) -> int:
        self._prune()
        return len(self._event_ts.get(name, ()))

    def _get_rate_per_hour(self, name: str) -> float:
        count = self._get_event_count(name)
        if self.window_sec <= 0:
            return float(count)
        return count * (3600.0 / self.window_sec)

    def _get_stale_ratio(self) -> float:
        self._prune()
        total = len(self._decision_snapshot_events)
        if total <= 0:
            return 0.0
        stale = sum(
            1 for _, is_fallback in self._decision_snapshot_events if is_fallback
        )
        return stale / float(total)

    def get_snapshot(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        for event_name, threshold_key in self.EVENT_TO_THRESHOLD.items():
            metrics[threshold_key] = self._get_rate_per_hour(event_name)
        metrics["stale_ratio"] = self._get_stale_ratio()
        metrics["window_sec"] = self.window_sec
        return metrics

    def evaluate_alerts(self) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        now = time.time()
        alerts: List[Dict[str, Any]] = []

        for event_name, threshold_key in self.EVENT_TO_THRESHOLD.items():
            threshold = self.thresholds.get(threshold_key)
            if threshold is None:
                continue
            value = self._get_rate_per_hour(event_name)
            if value <= float(threshold):
                continue
            if (
                now - self._last_alert_ts.get(threshold_key, 0.0)
                < self.alert_cooldown_sec
            ):
                continue
            self._last_alert_ts[threshold_key] = now
            alerts.append(
                {
                    "metric": threshold_key,
                    "value": value,
                    "threshold": float(threshold),
                    "window_sec": self.window_sec,
                }
            )

        stale_threshold = self.thresholds.get("stale_ratio_max")
        if stale_threshold is not None:
            stale_ratio = self._get_stale_ratio()
            if stale_ratio > float(stale_threshold):
                key = "stale_ratio_max"
                if now - self._last_alert_ts.get(key, 0.0) >= self.alert_cooldown_sec:
                    self._last_alert_ts[key] = now
                    alerts.append(
                        {
                            "metric": key,
                            "value": stale_ratio,
                            "threshold": float(stale_threshold),
                            "window_sec": self.window_sec,
                        }
                    )

        return alerts

    def emit_alerts(self) -> List[Dict[str, Any]]:
        alerts = self.evaluate_alerts()
        if not alerts:
            return alerts
        for alert in alerts:
            metric = alert["metric"]
            value = alert["value"]
            threshold = alert["threshold"]
            message = (
                f"SLO breach: {metric}={value:.3f} > {threshold:.3f} "
                f"(window={self.window_sec:.0f}s)"
            )
            if self.alert_manager:
                try:
                    self.alert_manager.send_alert(message, level="warning")
                except Exception as exc:
                    logger.debug(f"SLOMonitor alert manager error: {exc}")
            logger.warning(message)
        return alerts
