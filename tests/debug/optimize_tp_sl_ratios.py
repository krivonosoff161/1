"""
Комплексный тест для оптимизации TP/SL соотношений
Тестирует разные комбинации для максимизации профита
"""

import csv
import itertools
from typing import Dict, List, Tuple

def optimize_tp_sl_ratios(log_file_path: str) -> Dict:
    """Оптимизация TP/SL соотношений"""

    print('🎯 ОПТИМИЗАЦИЯ TP/SL СООТНОШЕНИЙ')
    print('=' * 50)

    # Читаем данные
    positions = []
    with open(log_file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['record_type'] == 'trades':
                positions.append(row)

    if not positions:
        print("❌ Нет данных о сделках")
        return {}

    print(f'📈 Анализ {len(positions)} сделок')

    # Текущая статистика
    current_pnl = sum(float(p.get('net_pnl', 0)) for p in positions if p.get('net_pnl'))
    win_rate = len([p for p in positions if float(p.get('net_pnl', 0)) > 0]) / len(positions) * 100

    print(f'📊 ТЕКУЩАЯ СТАТИСТИКА:')
    print(f'   P&L: {current_pnl:.2f} USDT')
    print(f'   Win Rate: {win_rate:.1f}%')

    # Возможные TP/SL соотношения для тестирования
    tp_ratios = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]  # TP/SL ratios
    sl_multipliers = [0.5, 1.0, 1.5, 2.0]  # SL multipliers for ATR

    print(f'\n🔄 ТЕСТИРОВАНИЕ КОМБИНАЦИЙ...')

    best_result = {
        'tp_ratio': None,
        'sl_multiplier': None,
        'pnl': float('-inf'),
        'win_rate': 0,
        'total_trades': 0,
        'profit_factor': 0
    }

    results = []

    for tp_ratio, sl_mult in itertools.product(tp_ratios, sl_multipliers):
        # Симуляция результатов с новыми TP/SL
        simulated_pnl = 0
        wins = 0
        losses = 0
        gross_profit = 0
        gross_loss = 0

        for pos in positions:
            try:
                entry_price = float(pos.get('entry_price', 0))
                exit_price = float(pos.get('exit_price', 0))
                side = pos.get('side', 'long')
                reason = pos.get('reason', '')

                if entry_price == 0 or exit_price == 0:
                    continue

                # Расчет типичного ATR (примерно 1-2% от цены)
                atr = entry_price * 0.015  # Предполагаем 1.5% ATR

                # Расчет SL и TP
                if side == 'long':
                    sl_price = entry_price - (atr * sl_mult)
                    tp_price = entry_price + (atr * sl_mult * tp_ratio)
                else:
                    sl_price = entry_price + (atr * sl_mult)
                    tp_price = entry_price - (atr * sl_mult * tp_ratio)

                # Симуляция выхода на основе новой логики TP/SL
                pnl = float(pos.get('net_pnl', 0))

                # Определяем, был бы TP или SL с новыми настройками
                if side == 'long':
                    if exit_price >= tp_price:
                        # TP hit - увеличиваем профит
                        simulated_pnl += pnl * tp_ratio
                        wins += 1
                        gross_profit += pnl * tp_ratio
                    elif exit_price <= sl_price:
                        # SL hit - уменьшаем лосс
                        simulated_pnl += pnl / sl_mult
                        losses += 1
                        gross_loss += abs(pnl) / sl_mult
                    else:
                        # Обычный выход
                        simulated_pnl += pnl
                        if pnl > 0:
                            wins += 1
                            gross_profit += pnl
                        else:
                            losses += 1
                            gross_loss += abs(pnl)
                else:
                    # Аналогично для short
                    if exit_price <= tp_price:
                        simulated_pnl += pnl * tp_ratio
                        wins += 1
                        gross_profit += pnl * tp_ratio
                    elif exit_price >= sl_price:
                        simulated_pnl += pnl / sl_mult
                        losses += 1
                        gross_loss += abs(pnl) / sl_mult
                    else:
                        simulated_pnl += pnl
                        if pnl > 0:
                            wins += 1
                            gross_profit += pnl
                        else:
                            losses += 1
                            gross_loss += abs(pnl)

            except (ValueError, TypeError):
                continue

        total_trades = wins + losses
        if total_trades > 0:
            win_rate_sim = wins / total_trades * 100
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

            result = {
                'tp_ratio': tp_ratio,
                'sl_multiplier': sl_mult,
                'pnl': simulated_pnl,
                'win_rate': win_rate_sim,
                'total_trades': total_trades,
                'profit_factor': profit_factor
            }
            results.append(result)

            # Обновляем лучший результат
            if simulated_pnl > best_result['pnl']:
                best_result = result.copy()

    # Сортировка результатов
    results.sort(key=lambda x: x['pnl'], reverse=True)

    print(f'\n🏆 ЛУЧШИЕ РЕЗУЛЬТАТЫ:')
    print(f'   TP/SL Ratio: {best_result["tp_ratio"]}')
    print(f'   SL Multiplier: {best_result["sl_multiplier"]}')
    print(f'   P&L: {best_result["pnl"]:.2f} USDT')
    print(f'   Win Rate: {best_result["win_rate"]:.1f}%')
    print(f'   Profit Factor: {best_result["profit_factor"]:.2f}')

    print(f'\n📋 ТОП-5 КОМБИНАЦИЙ:')
    for i, result in enumerate(results[:5], 1):
        print(f'   {i}. TP:{result["tp_ratio"]} SL:{result["sl_multiplier"]} | P&L:{result["pnl"]:.2f} | WR:{result["win_rate"]:.1f}% | PF:{result["profit_factor"]:.2f}')

    # Сравнение с текущими
    improvement = best_result['pnl'] - current_pnl
    print(f'\n📈 СРАВНЕНИЕ:')
    print(f'   Текущий P&L: {current_pnl:.2f} USDT')
    print(f'   Оптимизированный: {best_result["pnl"]:.2f} USDT')
    print(f'   Улучшение: {improvement:.2f} USDT ({improvement/current_pnl*100 if current_pnl != 0 else 0:.1f}%)')

    return {
        'best_result': best_result,
        'all_results': results,
        'current_stats': {
            'pnl': current_pnl,
            'win_rate': win_rate
        },
        'improvement': improvement
    }

if __name__ == "__main__":
    from pathlib import Path
    log_file = "logs/futures/archived/logs_2026-01-05_19-12-19/all_data_2026-01-05.csv"
    if Path(log_file).exists():
        optimize_tp_sl_ratios(log_file)
    else:
        print(f"❌ Файл {log_file} не найден")