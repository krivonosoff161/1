"""
Скрипт для анализа логов торговли и выявления проблем убыточности
"""
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

@dataclass
class Trade:
    """Модель сделки"""
    timestamp: datetime
    symbol: str
    direction: str  # LONG/SHORT
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    reason: str  # Причина закрытия
    duration: float = 0.0  # В минутах

@dataclass
class TradingMetrics:
    """Метрики торговли"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_win_loss_ratio: float = 0.0
    max_consecutive_losses: int = 0
    
    trades_by_symbol: Dict[str, int] = field(default_factory=dict)
    pnl_by_symbol: Dict[str, float] = field(default_factory=dict)
    trades_by_reason: Dict[str, int] = field(default_factory=dict)

class LogAnalyzer:
    """Анализатор логов торговли"""
    
    def __init__(self, log_dir: str):
        self.log_dir = Path(log_dir)
        self.trades: List[Trade] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
        
    def parse_logs(self):
        """Парсинг логов"""
        print(f"🔍 Анализ логов в: {self.log_dir}")
        
        # Ищем все файлы логов
        bot_log = self.log_dir / "bot.log"
        trades_log = self.log_dir / "trades.log"
        
        if bot_log.exists():
            self._parse_bot_log(bot_log)
        
        if trades_log.exists():
            self._parse_trades_log(trades_log)
        
        print(f"✅ Найдено сделок: {len(self.trades)}")
        print(f"⚠️  Ошибок: {len(self.errors)}")
        print(f"⚡ Предупреждений: {len(self.warnings)}")
    
    def _parse_bot_log(self, log_file: Path):
        """Парсинг основного лога"""
        print(f"📄 Парсинг {log_file.name}...")
        
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                # Ищем ошибки
                if 'ERROR' in line:
                    self.errors.append(line.strip())
                
                # Ищем предупреждения о проблемах
                if 'WARNING' in line or 'Stop-loss' in line:
                    self.warnings.append(line.strip())
                
                # Парсим информацию о закрытии позиций
                if 'Position closed' in line or 'Закрыта позиция' in line:
                    trade = self._extract_trade_from_line(line)
                    if trade:
                        self.trades.append(trade)
    
    def _parse_trades_log(self, log_file: Path):
        """Парсинг лога сделок"""
        print(f"📄 Парсинг {log_file.name}...")
        
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if 'TRADE' in line:
                    trade = self._extract_trade_from_line(line)
                    if trade:
                        self.trades.append(trade)
    
    def _extract_trade_from_line(self, line: str) -> Trade:
        """Извлечение данных о сделке из строки лога"""
        try:
            # Парсим timestamp
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S') if timestamp_match else datetime.now()
            
            # Парсим символ
            symbol_match = re.search(r'(BTC-USDT|ETH-USDT|[A-Z]+-USDT)', line)
            symbol = symbol_match.group(1) if symbol_match else "UNKNOWN"
            
            # Парсим направление
            direction = "LONG" if "LONG" in line else "SHORT"
            
            # Парсим цены
            price_match = re.search(r'entry[:\s]+(\d+\.?\d*).+exit[:\s]+(\d+\.?\d*)', line, re.IGNORECASE)
            if not price_match:
                price_match = re.search(r'(\d+\.?\d+).+->.+(\d+\.?\d+)', line)
            
            entry_price = float(price_match.group(1)) if price_match else 0.0
            exit_price = float(price_match.group(2)) if price_match else 0.0
            
            # Парсим PnL
            pnl_match = re.search(r'P&L[:\s]+([-+]?\d+\.?\d*)', line, re.IGNORECASE)
            if not pnl_match:
                pnl_match = re.search(r'([-+]?\d+\.?\d+)\s*USDT', line)
            
            pnl = float(pnl_match.group(1)) if pnl_match else 0.0
            
            # Парсим процент PnL
            pnl_percent_match = re.search(r'([-+]?\d+\.?\d+)%', line)
            pnl_percent = float(pnl_percent_match.group(1)) if pnl_percent_match else 0.0
            
            # Парсим причину
            reason = "unknown"
            if "take-profit" in line.lower() or "tp" in line.lower():
                reason = "take_profit"
            elif "stop-loss" in line.lower() or "sl" in line.lower():
                reason = "stop_loss"
            elif "time" in line.lower():
                reason = "time_limit"
            elif "trailing" in line.lower():
                reason = "trailing_stop"
            
            return Trade(
                timestamp=timestamp,
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=0.0,  # Может быть не в логе
                pnl=pnl,
                pnl_percent=pnl_percent,
                reason=reason
            )
        except Exception as e:
            print(f"⚠️  Ошибка парсинга строки: {e}")
            return None
    
    def calculate_metrics(self) -> TradingMetrics:
        """Расчет метрик производительности"""
        metrics = TradingMetrics()
        
        if not self.trades:
            return metrics
        
        metrics.total_trades = len(self.trades)
        
        wins = []
        losses = []
        consecutive_losses = 0
        max_consecutive_losses = 0
        
        for trade in self.trades:
            # Общий PnL
            metrics.total_pnl += trade.pnl
            
            # По символам
            metrics.trades_by_symbol[trade.symbol] = metrics.trades_by_symbol.get(trade.symbol, 0) + 1
            metrics.pnl_by_symbol[trade.symbol] = metrics.pnl_by_symbol.get(trade.symbol, 0.0) + trade.pnl
            
            # По причинам закрытия
            metrics.trades_by_reason[trade.reason] = metrics.trades_by_reason.get(trade.reason, 0) + 1
            
            # Прибыльные vs убыточные
            if trade.pnl > 0:
                metrics.winning_trades += 1
                wins.append(trade.pnl)
                consecutive_losses = 0
            else:
                metrics.losing_trades += 1
                losses.append(abs(trade.pnl))
                consecutive_losses += 1
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        
        # Расчет метрик
        metrics.win_rate = (metrics.winning_trades / metrics.total_trades * 100) if metrics.total_trades > 0 else 0
        metrics.avg_win = sum(wins) / len(wins) if wins else 0
        metrics.avg_loss = sum(losses) / len(losses) if losses else 0
        metrics.avg_win_loss_ratio = metrics.avg_win / metrics.avg_loss if metrics.avg_loss > 0 else 0
        
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        metrics.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        metrics.max_consecutive_losses = max_consecutive_losses
        
        return metrics
    
    def identify_problems(self, metrics: TradingMetrics) -> List[str]:
        """Выявление проблем в торговле"""
        problems = []
        
        # Проблема 1: Низкий Win Rate
        if metrics.win_rate < 40:
            problems.append(f"🔴 КРИТИЧНО: Очень низкий Win Rate ({metrics.win_rate:.1f}%). Проблемы с качеством сигналов!")
        elif metrics.win_rate < 50:
            problems.append(f"⚠️  Низкий Win Rate ({metrics.win_rate:.1f}%). Нужно улучшить фильтрацию сигналов.")
        
        # Проблема 2: Плохое соотношение Win/Loss
        if metrics.avg_win_loss_ratio < 1.0:
            problems.append(f"🔴 КРИТИЧНО: Средний убыток больше средней прибыли (ratio: {metrics.avg_win_loss_ratio:.2f})!")
        elif metrics.avg_win_loss_ratio < 1.5:
            problems.append(f"⚠️  Слабое соотношение прибыль/убыток ({metrics.avg_win_loss_ratio:.2f}). Рекомендуется > 1.5")
        
        # Проблема 3: Низкий Profit Factor
        if metrics.profit_factor < 1.0:
            problems.append(f"🔴 КРИТИЧНО: Profit Factor < 1 ({metrics.profit_factor:.2f}). Стратегия убыточна!")
        elif metrics.profit_factor < 1.5:
            problems.append(f"⚠️  Низкий Profit Factor ({metrics.profit_factor:.2f}). Цель > 1.5-2.0")
        
        # Проблема 4: Много последовательных убытков
        if metrics.max_consecutive_losses > 5:
            problems.append(f"🔴 Слишком много последовательных убытков ({metrics.max_consecutive_losses}). Проверьте фильтры!")
        
        # Проблема 5: Анализ причин закрытия
        if metrics.trades_by_reason.get('stop_loss', 0) > metrics.trades_by_reason.get('take_profit', 0):
            sl_count = metrics.trades_by_reason.get('stop_loss', 0)
            tp_count = metrics.trades_by_reason.get('take_profit', 0)
            problems.append(f"🔴 Stop-Loss срабатывает чаще ({sl_count}x), чем Take-Profit ({tp_count}x)!")
        
        # Проблема 6: Убыточные символы
        for symbol, pnl in metrics.pnl_by_symbol.items():
            if pnl < -10:  # Порог убытка
                problems.append(f"⚠️  Символ {symbol} сильно убыточен: {pnl:.2f} USDT")
        
        return problems
    
    def generate_report(self):
        """Генерация отчета"""
        print("\n" + "="*80)
        print("📊 ОТЧЕТ ПО АНАЛИЗУ ТОРГОВЛИ")
        print("="*80)
        
        metrics = self.calculate_metrics()
        
        # Общие метрики
        print(f"\n📈 ОБЩИЕ МЕТРИКИ:")
        print(f"   Всего сделок: {metrics.total_trades}")
        print(f"   Прибыльных: {metrics.winning_trades} ({metrics.win_rate:.1f}%)")
        print(f"   Убыточных: {metrics.losing_trades} ({100-metrics.win_rate:.1f}%)")
        print(f"   Общий P&L: {metrics.total_pnl:.2f} USDT")
        print(f"   Средняя прибыль: {metrics.avg_win:.2f} USDT")
        print(f"   Средний убыток: {metrics.avg_loss:.2f} USDT")
        print(f"   Win/Loss Ratio: {metrics.avg_win_loss_ratio:.2f}")
        print(f"   Profit Factor: {metrics.profit_factor:.2f}")
        print(f"   Макс. последовательных убытков: {metrics.max_consecutive_losses}")
        
        # По символам
        print(f"\n💹 ПО СИМВОЛАМ:")
        for symbol in sorted(metrics.trades_by_symbol.keys()):
            count = metrics.trades_by_symbol[symbol]
            pnl = metrics.pnl_by_symbol.get(symbol, 0)
            print(f"   {symbol}: {count} сделок, P&L: {pnl:.2f} USDT")
        
        # По причинам закрытия
        print(f"\n🎯 ПРИЧИНЫ ЗАКРЫТИЯ:")
        for reason, count in sorted(metrics.trades_by_reason.items(), key=lambda x: x[1], reverse=True):
            percent = count / metrics.total_trades * 100
            print(f"   {reason}: {count} ({percent:.1f}%)")
        
        # Проблемы
        problems = self.identify_problems(metrics)
        if problems:
            print(f"\n🚨 ВЫЯВЛЕННЫЕ ПРОБЛЕМЫ:")
            for i, problem in enumerate(problems, 1):
                print(f"   {i}. {problem}")
        
        # Топ ошибок
        if self.errors:
            print(f"\n❌ ТОП-5 ОШИБОК:")
            error_counts = defaultdict(int)
            for error in self.errors:
                # Упрощаем ошибку до ключевой фразы
                key = error[:100]
                error_counts[key] += 1
            
            for i, (error, count) in enumerate(sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5], 1):
                print(f"   {i}. [{count}x] {error}")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        self._generate_recommendations(metrics, problems)
        
        print("\n" + "="*80)
    
    def _generate_recommendations(self, metrics: TradingMetrics, problems: List[str]):
        """Генерация рекомендаций"""
        recommendations = []
        
        if metrics.win_rate < 50:
            recommendations.append("1. Усилить фильтрацию сигналов (повысить требования к confidence)")
            recommendations.append("   - Проверить работу MTF фильтра")
            recommendations.append("   - Добавить фильтр силы тренда (ADX)")
            recommendations.append("   - Увеличить минимальный confidence для входа")
        
        if metrics.avg_win_loss_ratio < 1.5:
            recommendations.append("2. Улучшить соотношение TP/SL:")
            recommendations.append("   - Увеличить TP (например, с 0.6% до 0.8-1.0%)")
            recommendations.append("   - Уменьшить SL (например, с 0.45% до 0.35-0.40%)")
            recommendations.append("   - Добавить trailing stop для фиксации прибыли")
        
        if metrics.trades_by_reason.get('stop_loss', 0) > metrics.total_trades * 0.5:
            recommendations.append("3. Частые стоп-лоссы указывают на:")
            recommendations.append("   - Слишком узкие стоп-лоссы")
            recommendations.append("   - Плохие точки входа (против тренда)")
            recommendations.append("   - Нужно проверить логику в signal_generator.py")
        
        if metrics.profit_factor < 1.5:
            recommendations.append("4. Низкий Profit Factor - рассмотрите:")
            recommendations.append("   - Временно остановить торговлю")
            recommendations.append("   - Протестировать на истории с новыми параметрами")
            recommendations.append("   - Пересмотреть стратегию входа/выхода")
        
        for rec in recommendations:
            print(f"   {rec}")
        
        if not recommendations:
            print("   ✅ Стратегия работает в рамках нормы. Продолжайте мониторинг.")

def main():
    """Главная функция"""
    import sys
    
    # Путь к логам
    if len(sys.argv) > 1:
        log_path = sys.argv[1]
    else:
        log_path = r"logs\futures\archived\staging_2026-01-06_02-41-05"
    
    analyzer = LogAnalyzer(log_path)
    analyzer.parse_logs()
    analyzer.generate_report()

if __name__ == "__main__":
    main()
