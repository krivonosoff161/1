import os
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.strategies.scalping.futures.metrics.log_replay import (
    apply_replay_to_slo_monitor,
    replay_archive_events,
)
from src.strategies.scalping.futures.metrics.slo_monitor import SLOMonitor


def test_replay_archive_events_counts(tmp_path: Path) -> None:
    archive = tmp_path / "archived"
    archive.mkdir(parents=True, exist_ok=True)

    info_log = archive / "info_2026-02-15.log"
    info_log.write_text(
        "\n".join(
            [
                "WS_STALE_SIGNAL_FALLBACK BTC-USDT fallback=rest",
                "WS_STALE_WATCHDOG global: stale=3/5",
                "EXIT_BLOCKED_PNL_MISMATCH ETH-USDT",
                "REENTRY_GUARD blocked entry: SOL-USDT LONG",
                "WS parse fallback for positions.pos: raw=''",
            ]
        ),
        encoding="utf-8",
    )

    error_log = archive / "errors_2026-02-15.log"
    error_log.write_text(
        "\n".join(
            [
                "Ошибка закрытия позиции BTC-USDT: cannot access local variable 'time'",
                "could not convert string to float: ''",
            ]
        ),
        encoding="utf-8",
    )

    counts = replay_archive_events(archive)
    assert counts["ws_stale_signal_fallback"] == 1
    assert counts["ws_stale_watchdog"] == 1
    assert counts["pnl_mismatch"] == 1
    assert counts["same_side_reentry_count"] == 1
    assert counts["close_pipeline_errors"] == 1
    assert counts["ws_parse_errors"] == 2


def test_replay_apply_to_monitor(tmp_path: Path) -> None:
    archive = tmp_path / "archived"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "info.log").write_text(
        "WS_STALE_SIGNAL_FALLBACK BTC-USDT fallback=rest\n"
        "WS_STALE_SIGNAL_FALLBACK ETH-USDT fallback=rest\n",
        encoding="utf-8",
    )

    monitor = SLOMonitor(
        config={
            "slo_monitor": {
                "window_sec": 3600,
                "thresholds": {"ws_stale_signal_fallback_per_hour": 1},
            }
        }
    )
    counts = replay_archive_events(archive)
    apply_replay_to_slo_monitor(counts, monitor)
    alerts = monitor.evaluate_alerts()
    assert any(a["metric"] == "ws_stale_signal_fallback_per_hour" for a in alerts)


@pytest.mark.skipif(
    not os.environ.get("FUTURES_REPLAY_ARCHIVE_DIR"),
    reason="FUTURES_REPLAY_ARCHIVE_DIR not set",
)
def test_replay_real_archive_dir_smoke() -> None:
    archive_path = Path(os.environ["FUTURES_REPLAY_ARCHIVE_DIR"])
    counts = replay_archive_events(archive_path)
    assert isinstance(counts, dict)
    assert "ws_stale_watchdog" in counts
