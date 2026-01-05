"""
Тест для анализа работы фильтров
Определяет, какие фильтры отсеивают слишком много сигналов
"""

import csv
import collections
from typing import Dict, List

def analyze_filter_effectiveness(log_file_path: str) -> Dict:
    """Анализ эффективности фильтров"""

    print('🔍 АНАЛИЗ ЭФФЕКТИВНОСТИ ФИЛЬТРОВ')
    print('=' * 50)

    # Читаем данные
    signals = []
    with open(log_file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['record_type'] == 'signals':
                signals.append(row)

    if not signals:
        print("❌ Нет данных о сигналах")
        return {}

    total_signals = len(signals)
    print(f'📈 Всего сигналов: {total_signals}')

    # Анализ по символам
    symbols = collections.Counter(row['symbol'] for row in signals)
    print(f'📊 Сигналы по символам: {dict(symbols)}')

    # Анализ по режимам
    regimes = collections.Counter(row['regime'] for row in signals)
    print(f'🎯 Режимы: {dict(regimes)}')

    # Анализ confidence/strength
    confidences = [float(row.get('confidence', 0)) for row in signals]
    strengths = [float(row.get('strength', 0)) for row in signals]

    print(f'🎚️ Confidence: min={min(confidences):.1f}, max={max(confidences):.1f}, avg={sum(confidences)/len(confidences):.1f}')
    print(f'💪 Strength: min={min(strengths):.1f}, max={max(strengths):.1f}, avg={sum(strengths)/len(strengths):.1f}')

    # Анализ фильтров (предполагаем, что есть поле filtered_reason)
    filtered_signals = [s for s in signals if s.get('filtered') == 'true']
    passed_signals = [s for s in signals if s.get('filtered') != 'true']

    print(f'✅ Прошедших фильтры: {len(passed_signals)}')
    print(f'❌ Отфильтрованных: {len(filtered_signals)}')

    if filtered_signals:
        filter_reasons = collections.Counter(row.get('filter_reason', 'unknown') for row in filtered_signals)
        print(f'📋 Причины фильтрации: {dict(filter_reasons)}')

    # Рекомендации по оптимизации
    print(f'\n💡 РЕКОМЕНДАЦИИ:')
    print(f'   • Конверсия сигналов: {len(passed_signals)/total_signals*100:.1f}%')

    if len(passed_signals)/total_signals < 0.2:
        print(f'   ⚠️ КРИТИЧНО: Конверсия слишком низкая! Фильтры отсеивают {100-len(passed_signals)/total_signals*100:.1f}% сигналов')
        print(f'   💡 Решение: Ослабить строгие фильтры для ranging режима')

    # Анализ по символам
    for symbol in symbols:
        symbol_signals = [s for s in signals if s['symbol'] == symbol]
        symbol_passed = [s for s in symbol_signals if s.get('filtered') != 'true']
        conversion = len(symbol_passed) / len(symbol_signals) * 100
        print(f'   📊 {symbol}: {len(symbol_passed)}/{len(symbol_signals)} ({conversion:.1f}%)')

    return {
        'total_signals': total_signals,
        'passed_signals': len(passed_signals),
        'filtered_signals': len(filtered_signals),
        'conversion_rate': len(passed_signals)/total_signals*100,
        'symbols_analysis': {symbol: len([s for s in signals if s['symbol'] == symbol and s.get('filtered') != 'true']) / count * 100
                           for symbol, count in symbols.items()},
        'regimes': dict(regimes)
    }

if __name__ == "__main__":
    from pathlib import Path
    log_file = "logs/futures/archived/logs_2026-01-05_19-12-19/all_data_2026-01-05.csv"
    if Path(log_file).exists():
        analyze_filter_effectiveness(log_file)
    else:
        print(f"❌ Файл {log_file} не найден")