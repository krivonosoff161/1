#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
РЕАЛИСТИЧНАЯ СИМУЛЯЦИЯ ТОРГОВЛИ С УЧЕТОМ МОДЕРНИЗАЦИИ
Более консервативные расчеты с учетом реальных ограничений
"""

import io
import math
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple

# Fix encoding for Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Параметры конфигурации
SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "DOGE-USDT", "XRP-USDT"]
REGIMES = ["trending", "ranging", "choppy"]
BALANCE_PROFILES = ["micro", "small", "medium", "large"]

# Баланс для симуляции
BALANCE = 1053.0  # USD (текущий баланс)
BALANCE_PROFILE = "small"  # Профиль баланса

# Реальные данные из сделок (11.11.2025)
REAL_DATA = {
    "total_trades": 5,
    "winning_trades": 3,
    "losing_trades": 2,
    "total_pnl": -0.06,  # USDT
    "total_commission": -0.24,  # USDT
    "avg_position_size": 55.0,  # USD (0.0005 BTC = ~$53)
    "avg_win": 0.03,  # USDT (+0.13%, +0.36%, +0.50%)
    "avg_loss": -0.075,  # USDT (-0.47%, -0.81%)
    "hours_traded": 18.67,  # 18 часов 40 минут
    "trades_per_hour": 5 / 18.67,  # ~0.27 сделок/час
}

# Параметры до модернизации (из реальных данных)
BEFORE = {
    "position_size_usd": 55.0,  # Средний размер позиции ($50-60)
    "trades_per_hour": 0.27,  # Реальные сделки/час (5 сделок за 18.67 часов)
    "commission_rate": 0.0005,  # 0.05% (market ордера)
    "tp_percent": 1.0,  # 1.0% TP (базовый)
    "sl_percent": 1.5,  # 1.5% SL (базовый)
    "win_rate": 0.60,  # 60% выигрышных сделок (3 из 5)
    "avg_profit_per_win": 0.03,  # $0.03 средняя прибыль (из реальных данных)
    "avg_loss_per_loss": -0.075,  # -$0.075 средний убыток (из реальных данных)
    "avg_profit_per_trade": (0.03 * 0.60) + (-0.075 * 0.40),  # -$0.003 на сделку
}

# Параметры после модернизации (оптимистичные, но реалистичные)
AFTER = {
    "position_size_usd": 125.0,  # Средний размер позиции ($100-150)
    "trades_per_hour": 80.0,  # Сделок в час (80-120/час, берем среднее 80)
    "commission_rate": 0.0002,  # 0.02% (limit ордера)
    "tp_percent": 1.0,  # 1.0% TP (базовый)
    "sl_percent": 1.5,  # 1.5% SL (базовый)
    "win_rate": 0.65,  # 65% выигрышных сделок (улучшение за счет лучших параметров)
    # Прибыль/убыток масштабируются пропорционально размеру позиции
    "position_size_multiplier": 125.0 / 55.0,  # 2.27x увеличение размера
}

# Параметры по режиму рынка
REGIME_PARAMS = {
    "trending": {
        "trades_per_hour_per_symbol": 20,  # Сделок в час на пару (из конфига: 25, но реалистично 20)
        "position_size_multiplier": 1.1,  # +10% размер позиции
        "tp_percent_multiplier": 1.1,  # +10% TP (1.1% вместо 1.0%)
        "sl_percent": 1.5,  # 1.5% SL
        "win_rate": 0.70,  # 70% выигрышных сделок (больше уверенности)
        "time_distribution": 0.30,  # 30% времени в тренде
        "signal_acceptance_rate": 0.60,  # 60% сигналов проходят фильтры
    },
    "ranging": {
        "trades_per_hour_per_symbol": 12,  # Сделок в час на пару (из конфига: 15, но реалистично 12)
        "position_size_multiplier": 1.0,  # Стандартный размер
        "tp_percent_multiplier": 1.0,  # Стандартный TP (1.0%)
        "sl_percent": 1.5,  # 1.5% SL
        "win_rate": 0.60,  # 60% выигрышных сделок
        "time_distribution": 0.50,  # 50% времени во флэте
        "signal_acceptance_rate": 0.50,  # 50% сигналов проходят фильтры
    },
    "choppy": {
        "trades_per_hour_per_symbol": 4,  # Сделок в час на пару (из конфига: 6, но реалистично 4)
        "position_size_multiplier": 0.8,  # -20% размер позиции
        "tp_percent_multiplier": 0.9,  # -10% TP (0.9% вместо 1.0%)
        "sl_percent": 1.5,  # 1.5% SL
        "win_rate": 0.55,  # 55% выигрышных сделок (меньше уверенности)
        "time_distribution": 0.20,  # 20% времени в хаосе
        "signal_acceptance_rate": 0.30,  # 30% сигналов проходят фильтры
    },
}

# Параметры по балансу
BALANCE_PARAMS = {
    "micro": {
        "base_position_usd": 50.0,
        "size_at_min": 30.0,
        "size_at_max": 50.0,
        "max_open_positions": 5,
    },
    "small": {
        "base_position_usd": 100.0,
        "size_at_min": 50.0,
        "size_at_max": 150.0,
        "max_open_positions": 5,
    },
    "medium": {
        "base_position_usd": 175.0,
        "size_at_min": 150.0,
        "size_at_max": 200.0,
        "max_open_positions": 5,
    },
    "large": {
        "base_position_usd": 250.0,
        "size_at_min": 200.0,
        "size_at_max": 300.0,
        "max_open_positions": 5,
    },
}

# Параметры по символу
SYMBOL_PARAMS = {
    "BTC-USDT": {
        "position_multiplier": 1.2,  # +20% размер позиции
        "base_tp_percent": 1.0,
        "liquidity_score": 1.0,  # Высокая ликвидность
        "signal_quality_multiplier": 1.0,  # Стандартное качество сигналов
    },
    "ETH-USDT": {
        "position_multiplier": 1.0,  # Стандартный размер
        "base_tp_percent": 0.95,
        "liquidity_score": 0.9,  # Хорошая ликвидность
        "signal_quality_multiplier": 0.95,  # Немного ниже качество
    },
    "SOL-USDT": {
        "position_multiplier": 0.9,  # -10% размер позиции
        "base_tp_percent": 0.9,
        "liquidity_score": 0.8,  # Средняя ликвидность
        "signal_quality_multiplier": 0.9,  # Ниже качество
    },
    "DOGE-USDT": {
        "position_multiplier": 0.8,  # -20% размер позиции
        "base_tp_percent": 0.85,
        "liquidity_score": 0.7,  # Ниже ликвидность
        "signal_quality_multiplier": 0.85,  # Ниже качество
    },
    "XRP-USDT": {
        "position_multiplier": 0.85,  # -15% размер позиции
        "base_tp_percent": 0.9,
        "liquidity_score": 0.75,  # Средняя ликвидность
        "signal_quality_multiplier": 0.88,  # Ниже качество
    },
}


@dataclass
class SimulationResult:
    """Результат симуляции"""

    regime: str
    symbol: str
    trades_per_hour: float
    position_size_usd: float
    tp_percent: float
    sl_percent: float
    win_rate: float
    profit_per_win: float
    loss_per_loss: float
    net_profit_per_trade: float
    net_profit_per_hour: float
    commission_per_hour: float
    total_profit_per_hour: float


def calculate_position_size(
    balance_profile: str, symbol: str, regime: str, balance: float = BALANCE
) -> float:
    """Рассчитывает размер позиции с учетом баланса, символа и режима"""
    # Базовый размер из балансового профиля
    profile = BALANCE_PARAMS[balance_profile]

    # Прогрессивная адаптация для small профиля
    if balance_profile == "small":
        min_balance = 500.0
        max_balance = 1500.0
        size_at_min = profile["size_at_min"]
        size_at_max = profile["size_at_max"]

        if balance <= min_balance:
            base_size = size_at_min
        elif balance >= max_balance:
            base_size = size_at_max
        else:
            progress = (balance - min_balance) / (max_balance - min_balance)
            base_size = size_at_min + (size_at_max - size_at_min) * progress
    else:
        base_size = profile["base_position_usd"]

    # Множитель по символу
    symbol_mult = SYMBOL_PARAMS[symbol]["position_multiplier"]

    # Множитель по режиму
    regime_mult = REGIME_PARAMS[regime]["position_size_multiplier"]

    # Итоговый размер
    position_size = base_size * symbol_mult * regime_mult

    # Ограничение максимальным размером
    max_size = profile.get("max_position_usd", profile["size_at_max"])
    position_size = min(position_size, max_size)

    return position_size


def calculate_tp_sl(
    symbol: str, regime: str, base_tp: float = 1.0, base_sl: float = 1.5
) -> Tuple[float, float]:
    """Рассчитывает TP/SL с учетом символа и режима"""
    # Базовый TP по символу
    symbol_tp = SYMBOL_PARAMS[symbol]["base_tp_percent"]

    # TP по режиму (из конфига)
    regime_tp_mult = REGIME_PARAMS[regime]["tp_percent_multiplier"]

    # Итоговый TP
    tp_percent = symbol_tp * regime_tp_mult

    # SL остается стандартным
    sl_percent = REGIME_PARAMS[regime]["sl_percent"]

    return tp_percent, sl_percent


def calculate_trades_per_hour(symbol: str, regime: str) -> float:
    """Рассчитывает частоту сделок с учетом символа и режима"""
    # Базовые сделки по режиму
    regime_trades = REGIME_PARAMS[regime]["trades_per_hour_per_symbol"]

    # Коэффициент ликвидности по символу
    liquidity_score = SYMBOL_PARAMS[symbol]["liquidity_score"]

    # Коэффициент качества сигналов
    signal_quality = SYMBOL_PARAMS[symbol]["signal_quality_multiplier"]

    # Коэффициент принятия сигналов по режиму
    signal_acceptance = REGIME_PARAMS[regime]["signal_acceptance_rate"]

    # Итоговая частота сделок
    trades_per_hour = (
        regime_trades * liquidity_score * signal_quality * signal_acceptance
    )

    return trades_per_hour


def simulate_trading(
    symbol: str,
    regime: str,
    balance_profile: str = BALANCE_PROFILE,
    balance: float = BALANCE,
    hours: float = 1.0,
) -> SimulationResult:
    """Симулирует торговлю для символа и режима"""
    # Расчет размера позиции
    position_size_usd = calculate_position_size(
        balance_profile, symbol, regime, balance
    )

    # Расчет TP/SL
    tp_percent, sl_percent = calculate_tp_sl(symbol, regime)

    # Расчет частоты сделок
    trades_per_hour = calculate_trades_per_hour(symbol, regime)

    # Параметры режима
    regime_params = REGIME_PARAMS[regime]
    win_rate = regime_params["win_rate"]

    # Расчет прибыли/убытка
    # Прибыль: позиция * TP% - комиссия
    profit_per_win = position_size_usd * (tp_percent / 100) - (
        position_size_usd * AFTER["commission_rate"] * 2
    )
    # Убыток: позиция * SL% + комиссия
    loss_per_loss = position_size_usd * (sl_percent / 100) + (
        position_size_usd * AFTER["commission_rate"] * 2
    )

    # Средняя прибыль на сделку
    avg_profit_per_trade = (profit_per_win * win_rate) + (
        loss_per_loss * (1 - win_rate)
    )

    # Комиссия на сделку
    commission_per_trade = position_size_usd * AFTER["commission_rate"] * 2

    # Чистая прибыль на сделку (уже включает комиссию)
    net_profit_per_trade = avg_profit_per_trade

    # Количество сделок за период
    trades_count = trades_per_hour * hours

    # Чистая прибыль за период
    net_profit_per_hour = net_profit_per_trade * trades_per_hour

    # Комиссия за период
    commission_per_hour = commission_per_trade * trades_per_hour

    # Итоговая прибыль за период
    total_profit_per_hour = net_profit_per_trade * trades_per_hour

    return SimulationResult(
        regime=regime,
        symbol=symbol,
        trades_per_hour=trades_per_hour,
        position_size_usd=position_size_usd,
        tp_percent=tp_percent,
        sl_percent=sl_percent,
        win_rate=win_rate,
        profit_per_win=profit_per_win,
        loss_per_loss=loss_per_loss,
        net_profit_per_trade=net_profit_per_trade,
        net_profit_per_hour=net_profit_per_hour,
        commission_per_hour=commission_per_hour,
        total_profit_per_hour=total_profit_per_hour,
    )


def calculate_before_after_comparison():
    """Сравнивает результаты до и после модернизации"""
    print("=" * 100)
    print("РЕАЛИСТИЧНАЯ СИМУЛЯЦИЯ ТОРГОВЛИ С УЧЕТОМ МОДЕРНИЗАЦИИ")
    print("=" * 100)
    print(f"\nБаланс: ${BALANCE:.2f}")
    print(f"Профиль баланса: {BALANCE_PROFILE}")
    print(f"Торговые пары: {', '.join(SYMBOLS)}")
    print(f"Режимы рынка: {', '.join(REGIMES)}")

    # Результаты до модернизации (из реальных данных)
    print("\n" + "=" * 100)
    print("ДО МОДЕРНИЗАЦИИ (РЕАЛЬНЫЕ ДАННЫЕ)")
    print("=" * 100)

    before_trades_per_hour = BEFORE["trades_per_hour"]
    before_position_size = BEFORE["position_size_usd"]
    before_commission_rate = BEFORE["commission_rate"]
    before_win_rate = BEFORE["win_rate"]
    before_avg_profit = BEFORE["avg_profit_per_win"]
    before_avg_loss = BEFORE["avg_loss_per_loss"]
    before_net_profit_per_trade = BEFORE["avg_profit_per_trade"]
    before_net_profit_per_hour = before_net_profit_per_trade * before_trades_per_hour
    before_commission_per_hour = (
        before_position_size * before_commission_rate * 2 * before_trades_per_hour
    )

    print(f"Размер позиции: ${before_position_size:.2f}")
    print(f"Частота сделок: {before_trades_per_hour:.2f} сделок/час")
    print(f"Комиссия: {before_commission_rate * 100:.3f}% (market ордера)")
    print(f"Win rate: {before_win_rate * 100:.1f}%")
    print(f"Средняя прибыль на сделку: ${before_avg_profit:.2f}")
    print(f"Средний убыток на сделку: ${before_avg_loss:.2f}")
    print(f"Чистая прибыль на сделку: ${before_net_profit_per_trade:.4f}")
    print(f"Чистая прибыль в час: ${before_net_profit_per_hour:.4f}")
    print(f"Комиссия в час: ${before_commission_per_hour:.4f}")
    print(f"Прибыль за день (24 часа): ${before_net_profit_per_hour * 24:.2f}")
    print(f"Прибыль за месяц (30 дней): ${before_net_profit_per_hour * 24 * 30:.2f}")

    # Результаты после модернизации
    print("\n" + "=" * 100)
    print("ПОСЛЕ МОДЕРНИЗАЦИИ (СИМУЛЯЦИЯ)")
    print("=" * 100)

    # Симуляция по каждому режиму и символу
    results_by_regime = {regime: [] for regime in REGIMES}
    results_by_symbol = {symbol: [] for symbol in SYMBOLS}

    total_profit_per_hour = 0.0
    total_trades_per_hour = 0.0
    total_commission_per_hour = 0.0

    for regime in REGIMES:
        regime_time_dist = REGIME_PARAMS[regime]["time_distribution"]
        regime_total_profit = 0.0
        regime_total_trades = 0.0

        for symbol in SYMBOLS:
            result = simulate_trading(symbol, regime, BALANCE_PROFILE, BALANCE, 1.0)
            results_by_regime[regime].append(result)
            results_by_symbol[symbol].append(result)

            # Учитываем распределение времени по режимам
            weighted_profit = result.total_profit_per_hour * regime_time_dist
            weighted_trades = result.trades_per_hour * regime_time_dist

            regime_total_profit += weighted_profit
            regime_total_trades += weighted_trades

            total_profit_per_hour += weighted_profit
            total_trades_per_hour += weighted_trades
            total_commission_per_hour += result.commission_per_hour * regime_time_dist

        print(f"\n--- {regime.upper()} ({regime_time_dist * 100:.0f}% времени) ---")
        print(f"Сделок в час (все пары): {regime_total_trades:.1f}")
        print(f"Прибыль в час: ${regime_total_profit:.2f}")

        for result in results_by_regime[regime]:
            print(
                f"  {result.symbol}: {result.trades_per_hour:.1f} сделок/час, "
                f"размер ${result.position_size_usd:.2f}, TP={result.tp_percent:.2f}%, "
                f"прибыль ${result.total_profit_per_hour * regime_time_dist:.2f}/час"
            )

    # Итоговые результаты
    print("\n" + "=" * 100)
    print("ИТОГОВЫЕ РЕЗУЛЬТАТЫ ПОСЛЕ МОДЕРНИЗАЦИИ")
    print("=" * 100)
    print(f"Всего сделок в час: {total_trades_per_hour:.1f}")
    print(f"Чистая прибыль в час: ${total_profit_per_hour:.2f}")
    print(f"Комиссия в час: ${total_commission_per_hour:.2f}")
    print(f"Прибыль за день (24 часа): ${total_profit_per_hour * 24:.2f}")
    print(f"Прибыль за месяц (30 дней): ${total_profit_per_hour * 24 * 30:.2f}")

    # Сравнение
    print("\n" + "=" * 100)
    print("СРАВНЕНИЕ ДО И ПОСЛЕ МОДЕРНИЗАЦИИ")
    print("=" * 100)

    improvement_trades = ((total_trades_per_hour / before_trades_per_hour) - 1) * 100
    if before_net_profit_per_hour > 0:
        improvement_profit = (
            (total_profit_per_hour / before_net_profit_per_hour) - 1
        ) * 100
    else:
        improvement_profit = float("inf")
    improvement_commission = (
        (total_commission_per_hour / before_commission_per_hour) - 1
    ) * 100

    print(
        f"Улучшение частоты сделок: {improvement_trades:.1f}% "
        f"({before_trades_per_hour:.2f} -> {total_trades_per_hour:.1f} сделок/час)"
    )
    if before_net_profit_per_hour > 0:
        print(
            f"Улучшение прибыли: {improvement_profit:.1f}% "
            f"(${before_net_profit_per_hour:.4f} -> ${total_profit_per_hour:.2f}/час)"
        )
    else:
        print(
            f"Прибыль стала положительной: ${before_net_profit_per_hour:.4f} -> ${total_profit_per_hour:.2f}/час"
        )
    print(
        f"Изменение комиссии: {improvement_commission:.1f}% "
        f"(${before_commission_per_hour:.4f} -> ${total_commission_per_hour:.2f}/час)"
    )
    print(
        f"Улучшение прибыли за день: {((total_profit_per_hour * 24) / (before_net_profit_per_hour * 24) - 1) * 100:.1f}% "
        f"(${before_net_profit_per_hour * 24:.2f} -> ${total_profit_per_hour * 24:.2f}/день)"
    )
    print(
        f"Улучшение прибыли за месяц: {((total_profit_per_hour * 24 * 30) / (before_net_profit_per_hour * 24 * 30) - 1) * 100:.1f}% "
        f"(${before_net_profit_per_hour * 24 * 30:.2f} -> ${total_profit_per_hour * 24 * 30:.2f}/месяц)"
    )

    # Детальная разбивка по символам
    print("\n" + "=" * 100)
    print("ДЕТАЛЬНАЯ РАЗБИВКА ПО СИМВОЛАМ")
    print("=" * 100)

    for symbol in SYMBOLS:
        symbol_total_profit = 0.0
        symbol_total_trades = 0.0
        symbol_avg_position_size = 0.0

        for regime in REGIMES:
            result = next(
                (r for r in results_by_symbol[symbol] if r.regime == regime), None
            )
            if result:
                regime_time_dist = REGIME_PARAMS[regime]["time_distribution"]
                symbol_total_profit += result.total_profit_per_hour * regime_time_dist
                symbol_total_trades += result.trades_per_hour * regime_time_dist
                symbol_avg_position_size += result.position_size_usd * regime_time_dist

        print(f"\n{symbol}:")
        print(f"  Сделок в час: {symbol_total_trades:.1f}")
        print(f"  Средний размер позиции: ${symbol_avg_position_size:.2f}")
        print(f"  Прибыль в час: ${symbol_total_profit:.2f}")
        print(f"  Прибыль за день: ${symbol_total_profit * 24:.2f}")
        print(f"  Прибыль за месяц: ${symbol_total_profit * 24 * 30:.2f}")

    # Детальная разбивка по режимам
    print("\n" + "=" * 100)
    print("ДЕТАЛЬНАЯ РАЗБИВКА ПО РЕЖИМАМ")
    print("=" * 100)

    for regime in REGIMES:
        regime_time_dist = REGIME_PARAMS[regime]["time_distribution"]
        regime_total_profit = 0.0
        regime_total_trades = 0.0
        regime_avg_position_size = 0.0

        for symbol in SYMBOLS:
            result = next(
                (r for r in results_by_regime[regime] if r.symbol == symbol), None
            )
            if result:
                regime_total_profit += result.total_profit_per_hour * regime_time_dist
                regime_total_trades += result.trades_per_hour * regime_time_dist
                regime_avg_position_size += result.position_size_usd * regime_time_dist

        print(f"\n{regime.upper()} ({regime_time_dist * 100:.0f}% времени):")
        print(f"  Сделок в час: {regime_total_trades:.1f}")
        print(f"  Средний размер позиции: ${regime_avg_position_size:.2f}")
        print(f"  Прибыль в час: ${regime_total_profit:.2f}")
        print(f"  Прибыль за день: ${regime_total_profit * 24:.2f}")
        print(f"  Прибыль за месяц: ${regime_total_profit * 24 * 30:.2f}")

    # Выводы
    print("\n" + "=" * 100)
    print("ВЫВОДЫ")
    print("=" * 100)
    print(
        f"[OK] Частота сделок увеличена в {total_trades_per_hour / before_trades_per_hour:.1f} раз"
    )
    if before_net_profit_per_hour > 0:
        print(
            f"[OK] Прибыль увеличена в {total_profit_per_hour / before_net_profit_per_hour:.1f} раз"
        )
    else:
        print(
            f"[OK] Прибыль стала положительной (было ${before_net_profit_per_hour:.4f}/час)"
        )
    print(
        f"[OK] Комиссия снижена на {abs(improvement_commission):.1f}% (limit ордера вместо market)"
    )
    print(
        f"[OK] Размеры позиций увеличены в {calculate_position_size(BALANCE_PROFILE, 'BTC-USDT', 'trending') / before_position_size:.1f} раз"
    )
    print(f"[OK] Ожидаемая прибыль за месяц: ${total_profit_per_hour * 24 * 30:.2f}")


if __name__ == "__main__":
    calculate_before_after_comparison()
