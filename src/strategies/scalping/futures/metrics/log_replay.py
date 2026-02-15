from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable

EVENT_PATTERNS = {
    "ws_stale_signal_fallback": (
        "WS_STALE_SIGNAL_FALLBACK",
        "SignalGenerator: WebSocket цена",
    ),
    "ws_stale_watchdog": ("WS_STALE_WATCHDOG",),
    "close_pipeline_errors": (
        "Ошибка закрытия позиции",
        "Error closing position",
        "cannot access local variable 'time'",
    ),
    "pnl_mismatch": ("EXIT_BLOCKED_PNL_MISMATCH", "EXIT_DEFERRED_PNL_MISMATCH"),
    "ws_parse_errors": (
        "could not convert string to float: ''",
        "WS parse fallback for",
    ),
    "same_side_reentry_count": ("REENTRY_GUARD blocked entry",),
}


def _iter_log_files(archive_dir: Path) -> Iterable[Path]:
    if not archive_dir.exists():
        return []
    return sorted(p for p in archive_dir.rglob("*.log") if p.is_file())


def replay_archive_events(archive_dir: Path) -> Dict[str, int]:
    """
    Replay archived logs and count SLO-related events.

    The function is intentionally lightweight and tolerant to mixed encodings.
    """
    counts: Dict[str, int] = {key: 0 for key in EVENT_PATTERNS}
    for log_path in _iter_log_files(archive_dir):
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            for event_name, patterns in EVENT_PATTERNS.items():
                if any(pattern in line for pattern in patterns):
                    counts[event_name] += 1
                    break
    return counts


def apply_replay_to_slo_monitor(event_counts: Dict[str, int], slo_monitor) -> None:
    """Push replayed event counts into SLOMonitor."""
    if not slo_monitor:
        return
    for event_name, count in event_counts.items():
        if count > 0:
            slo_monitor.record_event(event_name, count=count)
