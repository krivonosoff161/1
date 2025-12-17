"""
Единицы измерения и конвертации (futures).

Контракт:
- **pct points**: 0.8 означает 0.8% (не 80%). Для перевода в долю используем /100.
- **fraction**: 0.008 означает 0.8% (удобно для форматирования через {:.2%}).
- **bps**: 7.0 означает 7 bps = 0.07% = 0.0007 (fraction).
"""

from __future__ import annotations


def pct_points_to_fraction(pct_points: float) -> float:
    """0.8 -> 0.008"""
    return float(pct_points) / 100.0


def fraction_to_pct_points(frac: float) -> float:
    """0.008 -> 0.8"""
    return float(frac) * 100.0


def bps_to_fraction(bps: float) -> float:
    """7.0 bps -> 0.0007"""
    return float(bps) / 10000.0


def fraction_to_bps(frac: float) -> float:
    """0.0007 -> 7.0 bps"""
    return float(frac) * 10000.0
