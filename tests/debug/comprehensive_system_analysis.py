"""
Комплексный анализ всей торговой системы
Анализ по режимам, парам, системам и адаптивным параметрам
"""

import collections
import csv
from datetime import datetime
from typing import Dict, List


def comprehensive_system_analysis(log_file_path: str) -> Dict:
    """Комплексный анализ всей системы"""

    print("🔬 КОМПЛЕКСНЫЙ АНАЛИЗ ТОРГОВОЙ СИСТЕМЫ")
    print("=" * 60)

    # Читаем все данные
    all_data = []
    with open(log_file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_data.append(row)

    if not all_data:
        print("❌ Нет данных для анализа")
        return {}

    print(f"📊 Всего записей: {len(all_data)}")

    # Анализ сигналов
    signals = [row for row in all_data if row["record_type"] == "signals"]
    trades = [row for row in all_data if row["record_type"] == "trades"]
    positions_open = [row for row in all_data if row["record_type"] == "positions_open"]

    print(f"📈 Сигналов: {len(signals)}")
    print(f"💼 Сделок: {len(trades)}")
    print(f"📊 Открытых позиций: {len(positions_open)}")

    # === АНАЛИЗ ПО РЕЖИМАМ ===
    print(f"\n🎯 АНАЛИЗ ПО РЕЖИМАМ:")
    regime_analysis = analyze_by_regime(signals, trades)

    # === АНАЛИЗ ПО ПАРАМ ===
    print(f"\n📊 АНАЛИЗ ПО ПАРАМ:")
    pair_analysis = analyze_by_pairs(signals, trades)

    # === АНАЛИЗ СИСТЕМ ===
    print(f"\n⚙️ АНАЛИЗ СИСТЕМ:")
    system_analysis = analyze_systems(signals, trades)

    # === АНАЛИЗ АДАПТИВНЫХ ПАРАМЕТРОВ ===
    print(f"\n🔧 АНАЛИЗ АДАПТИВНЫХ ПАРАМЕТРОВ:")
    adaptive_analysis = analyze_adaptive_parameters(trades)

    # === ВРЕМЕННОЙ АНАЛИЗ ===
    print(f"\n🕐 ВРЕМЕННОЙ АНАЛИЗ:")
    time_analysis = analyze_time_patterns(signals, trades)

    # === ОБЩИЕ РЕКОМЕНДАЦИИ ===
    print(f"\n💡 ОБЩИЕ РЕКОМЕНДАЦИИ:")
    recommendations = generate_recommendations(
        regime_analysis,
        pair_analysis,
        system_analysis,
        adaptive_analysis,
        time_analysis,
    )

    return {
        "regime_analysis": regime_analysis,
        "pair_analysis": pair_analysis,
        "system_analysis": system_analysis,
        "adaptive_analysis": adaptive_analysis,
        "time_analysis": time_analysis,
        "recommendations": recommendations,
    }


def analyze_by_regime(signals: List[Dict], trades: List[Dict]) -> Dict:
    """Анализ по режимам рынка"""

    print(
        f'   📋 Режимы в сигналах: {collections.Counter(row.get("regime", "unknown") for row in signals)}'
    )
    print(
        f'   📋 Режимы в сделках: {collections.Counter(row.get("regime", "unknown") for row in trades)}'
    )

    regimes = {}
    for regime in set(row.get("regime", "unknown") for row in signals + trades):
        if regime == "unknown":
            continue

        regime_signals = [s for s in signals if s.get("regime") == regime]
        regime_trades = [t for t in trades if t.get("regime") == regime]

        if regime_signals:
            conversion = len(regime_trades) / len(regime_signals) * 100
        else:
            conversion = 0

        if regime_trades:
            pnl = sum(float(t.get("net_pnl", 0)) for t in regime_trades)
            win_rate = (
                len([t for t in regime_trades if float(t.get("net_pnl", 0)) > 0])
                / len(regime_trades)
                * 100
            )
            avg_duration = (
                sum(float(t.get("duration_sec", 0)) for t in regime_trades)
                / len(regime_trades)
                / 60
            )
        else:
            pnl = 0
            win_rate = 0
            avg_duration = 0

        regimes[regime] = {
            "signals": len(regime_signals),
            "trades": len(regime_trades),
            "conversion": conversion,
            "pnl": pnl,
            "win_rate": win_rate,
            "avg_duration": avg_duration,
        }

        print(
            f"   {regime.upper()}: {len(regime_signals)} сигн → {len(regime_trades)} сделок ({conversion:.1f}%) | P&L: {pnl:.2f} | WR: {win_rate:.1f}% | Avg: {avg_duration:.1f} мин"
        )

    return regimes


def analyze_by_pairs(signals: List[Dict], trades: List[Dict]) -> Dict:
    """Анализ по торговым парам"""

    pairs = {}
    all_symbols = set(row.get("symbol", "unknown") for row in signals + trades)

    for symbol in all_symbols:
        if symbol == "unknown":
            continue

        pair_signals = [s for s in signals if s.get("symbol") == symbol]
        pair_trades = [t for t in trades if t.get("symbol") == symbol]

        if pair_signals:
            conversion = len(pair_trades) / len(pair_signals) * 100
        else:
            conversion = 0

        if pair_trades:
            pnl = sum(float(t.get("net_pnl", 0)) for t in pair_trades)
            win_rate = (
                len([t for t in pair_trades if float(t.get("net_pnl", 0)) > 0])
                / len(pair_trades)
                * 100
            )
            reasons = collections.Counter(
                t.get("reason", "unknown") for t in pair_trades
            )
        else:
            pnl = 0
            win_rate = 0
            reasons = {}

        pairs[symbol] = {
            "signals": len(pair_signals),
            "trades": len(pair_trades),
            "conversion": conversion,
            "pnl": pnl,
            "win_rate": win_rate,
            "close_reasons": dict(reasons),
        }

        print(
            f"   {symbol}: {len(pair_signals)} сигн → {len(pair_trades)} сделок ({conversion:.1f}%) | P&L: {pnl:.2f} | WR: {win_rate:.1f}%"
        )

    return pairs


def analyze_systems(signals: List[Dict], trades: List[Dict]) -> Dict:
    """Анализ различных торговых систем"""

    # Анализ big profit системы
    big_profit_trades = [
        t
        for t in trades
        if "profit_harvest" in t.get("reason", "")
        or "max_holding" in t.get("reason", "")
    ]
    print(f"   🤑 Big Profit система: {len(big_profit_trades)} сделок")

    # Анализ системы rebounds
    rebound_signals = [
        s for s in signals if "rebound" in s.get("filters_passed", "").lower()
    ]
    rebound_trades = [
        t for t in trades if any("rebound" in str(t.get(k, "")) for k in t.keys())
    ]
    print(
        f"   🔄 Rebound система: {len(rebound_signals)} сигналов → {len(rebound_trades)} сделок"
    )

    # Анализ time-based системы
    time_signals = [s for s in signals if "time" in s.get("filters_passed", "").lower()]
    time_trades = [
        t for t in trades if float(t.get("duration_sec", 0)) > 1800
    ]  # >30 мин
    print(
        f"   🕐 Time-based система: {len(time_signals)} сигналов → {len(time_trades)} сделок"
    )

    return {
        "big_profit": {
            "trades": len(big_profit_trades),
            "pnl": sum(float(t.get("net_pnl", 0)) for t in big_profit_trades),
        },
        "rebounds": {"signals": len(rebound_signals), "trades": len(rebound_trades)},
        "time_based": {"signals": len(time_signals), "trades": len(time_trades)},
    }


def analyze_adaptive_parameters(trades: List[Dict]) -> Dict:
    """Анализ адаптивных параметров"""

    # Анализ TP/SL адаптивности
    tp_reasons = len([t for t in trades if "tp_reached" in t.get("reason", "")])
    sl_reasons = len([t for t in trades if "sl_reached" in t.get("reason", "")])

    print(
        f"   🎯 TP/SL адаптивность: TP {tp_reasons}, SL {sl_reasons} ({sl_reasons/(tp_reasons+sl_reasons)*100:.1f}% SL)"
    )

    # Анализ размеров позиций
    sizes = [float(t.get("size", 0)) for t in trades if t.get("size")]
    if sizes:
        print(
            f"   📏 Размеры позиций: min {min(sizes):.4f}, max {max(sizes):.4f}, avg {sum(sizes)/len(sizes):.4f}"
        )

    # Анализ левериджа (если есть)
    leverages = [float(t.get("leverage", 0)) for t in trades if t.get("leverage")]
    if leverages:
        print(
            f"   ⚡ Леверидж: min {min(leverages)}, max {max(leverages)}, avg {sum(leverages)/len(leverages):.1f}"
        )

    return {
        "tp_sl_ratio": sl_reasons / (tp_reasons + sl_reasons)
        if (tp_reasons + sl_reasons) > 0
        else 0,
        "position_sizes": sizes,
        "leverages": leverages,
    }


def analyze_time_patterns(signals: List[Dict], trades: List[Dict]) -> Dict:
    """Анализ временных паттернов"""

    # Анализ по часам
    signal_hours = []
    trade_hours = []

    for s in signals:
        try:
            dt = datetime.fromisoformat(s.get("timestamp", "").replace("Z", "+00:00"))
            signal_hours.append(dt.hour)
        except:
            pass

    for t in trades:
        try:
            dt = datetime.fromisoformat(t.get("timestamp", "").replace("Z", "+00:00"))
            trade_hours.append(dt.hour)
        except:
            pass

    if signal_hours:
        signal_hour_dist = collections.Counter(signal_hours)
        print(f"   📈 Сигналы по часам: {dict(signal_hour_dist.most_common(3))}")

    if trade_hours:
        trade_hour_dist = collections.Counter(trade_hours)
        print(f"   💼 Сделки по часам: {dict(trade_hour_dist.most_common(3))}")

    return {
        "signal_hours": dict(collections.Counter(signal_hours)),
        "trade_hours": dict(collections.Counter(trade_hours)),
    }


def generate_recommendations(
    regime_analysis, pair_analysis, system_analysis, adaptive_analysis, time_analysis
) -> List[str]:
    """Генерация рекомендаций"""

    recommendations = []

    # Анализ режимов
    best_regime = (
        max(regime_analysis.items(), key=lambda x: x[1]["pnl"])
        if regime_analysis
        else None
    )
    worst_regime = (
        min(regime_analysis.items(), key=lambda x: x[1]["pnl"])
        if regime_analysis
        else None
    )

    if best_regime and worst_regime:
        recommendations.append(
            f"• Лучший режим: {best_regime[0]} (P&L: {best_regime[1]['pnl']:.2f})"
        )
        recommendations.append(
            f"• Худший режим: {worst_regime[0]} (P&L: {worst_regime[1]['pnl']:.2f}) - требует настройки"
        )

    # Анализ пар
    best_pair = (
        max(pair_analysis.items(), key=lambda x: x[1]["pnl"]) if pair_analysis else None
    )
    worst_pair = (
        min(pair_analysis.items(), key=lambda x: x[1]["pnl"]) if pair_analysis else None
    )

    if best_pair and worst_pair:
        recommendations.append(
            f"• Лучшая пара: {best_pair[0]} (P&L: {best_pair[1]['pnl']:.2f})"
        )
        recommendations.append(
            f"• Худшая пара: {worst_pair[0]} (P&L: {worst_pair[1]['pnl']:.2f}) - адаптировать параметры"
        )

    # Анализ систем
    if system_analysis["big_profit"]["trades"] > 0:
        bp_pnl = system_analysis["big_profit"]["pnl"]
        recommendations.append(
            f"• Big Profit система: {bp_pnl:.2f} P&L - {'хорошая' if bp_pnl > 0 else 'нуждается в оптимизации'}"
        )

    # Общие рекомендации
    if adaptive_analysis["tp_sl_ratio"] > 0.7:
        recommendations.append(
            "• Критично: слишком много SL - оптимизировать TP/SL соотношение для каждого режима/пары"
        )

    recommendations.append(
        "• Необходимы индивидуальные параметры для каждой комбинации режим+пара"
    )
    recommendations.append("• Провести A/B тестирование параметров для каждого режима")

    for rec in recommendations:
        print(f"   {rec}")

    return recommendations


if __name__ == "__main__":
    from pathlib import Path

    log_file = "logs/futures/archived/logs_2026-01-05_19-12-19/all_data_2026-01-05.csv"
    if Path(log_file).exists():
        comprehensive_system_analysis(log_file)
    else:
        print(f"❌ Файл {log_file} не найден")
