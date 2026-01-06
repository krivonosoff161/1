"""
Главный engine для backtesting стратегии на исторических данных
Использует реальное API подключение к OKX для загрузки данных
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import json
from pathlib import Path
from loguru import logger
import random

@dataclass
class BacktestMetrics:
    """Метрики результатов backtesting"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_loss_ratio: float = 0.0
    max_consecutive_losses: int = 0
    trades: List[Dict] = field(default_factory=list)

class BacktestEngine:
    """Главный engine для backtesting"""
    
    def __init__(self, config, symbol: str = "BTC-USDT"):
        self.config = config
        self.symbol = symbol
        self.klines = []
        self.trades = []
        self.closed_trades = []
        self.iteration_count = 0
    
    async def run(
        self,
        start_date: str = "2025-12-01",
        end_date: str = "2026-01-06",
        timeframe: str = "1m",
        verbose: bool = True
    ) -> BacktestMetrics:
        """Запустить backtesting"""
        if verbose:
            print(f"\n{'='*80}")
            print(f"🔄 BACKTESTING: {self.symbol} ({start_date} → {end_date})")
            print(f"{'='*80}\n")
        
        try:
            # Загрузить данные
            if verbose:
                print(f"📥 Загружаем исторические данные...")
            self.klines = await self._load_historical_data(start_date, end_date)
            
            if not self.klines:
                logger.error(f"❌ Не удалось загрузить данные")
                return BacktestMetrics()
            
            if verbose:
                print(f"   ✅ Загружено {len(self.klines)} свечей\n")
            
            # Симуляция
            if verbose:
                print(f"⚙️  Запуск симуляции торговли...\n")
            
            for i, kline in enumerate(self.klines):
                if verbose and i % 1000 == 0 and i > 0:
                    print(f"   Обработано {i}/{len(self.klines)} свечей ({i/len(self.klines)*100:.1f}%)")
                
                # Проверить выходы
                await self._check_position_exits(kline)
                
                # Открыть позицию (случайно для demo)
                if i % 50 == 0 and len(self.trades) < 3:
                    await self._open_position(kline)
                
                self.iteration_count += 1
            
            if verbose:
                print(f"   ✅ Симуляция завершена\n")
            
            # Рассчитать метрики
            if verbose:
                print(f"📊 Расчет метрик...")
            metrics = self._calculate_metrics()
            
            # Вывести результаты
            if verbose:
                self._print_results(metrics)
            
            return metrics
        
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            raise
    
    async def run_with_params(
        self,
        start_date: str,
        end_date: str,
        tp_percent: float = None,
        sl_percent: float = None,
        verbose: bool = False
    ) -> BacktestMetrics:
        """Запустить с параметрами"""
        return await self.run(start_date, end_date, verbose=verbose)
    
    async def _load_historical_data(
        self,
        start_date: str,
        end_date: str
    ) -> List[List]:
        """Загрузить данные"""
        try:
            from src.clients.futures_client import FuturesClient
            client = FuturesClient(self.config)
            
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            
            all_klines = []
            current = start
            
            while current < end:
                try:
                    klines = await client.get_klines(
                        symbol=self.symbol,
                        timeframe="1m",
                        limit=100,
                        since=int(current.timestamp() * 1000)
                    )
                    
                    if not klines:
                        break
                    
                    all_klines.extend(klines)
                    current += timedelta(minutes=100)
                
                except Exception as e:
                    logger.warning(f"⚠️  Ошибка загрузки: {e}")
                    await asyncio.sleep(1)
            
            return all_klines if all_klines else await self._load_mock_data(start_date, end_date)
        
        except ImportError:
            return await self._load_mock_data(start_date, end_date)
    
    async def _load_mock_data(self, start_date: str, end_date: str) -> List[List]:
        """Загрузить mock данные"""
        logger.warning("⚠️  Используются mock данные (для тестирования)")
        
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        
        klines = []
        current = start
        base_price = 42000.0
        
        while current < end:
            open_price = base_price + random.uniform(-100, 100)
            close_price = open_price + random.uniform(-150, 150)
            high_price = max(open_price, close_price) + random.uniform(0, 50)
            low_price = min(open_price, close_price) - random.uniform(0, 50)
            
            timestamp = int(current.timestamp() * 1000)
            
            klines.append([
                timestamp,
                str(open_price),
                str(high_price),
                str(low_price),
                str(close_price),
                str(random.uniform(100, 500))
            ])
            
            base_price = close_price
            current += timedelta(minutes=1)
        
        return klines
    
    async def _open_position(self, kline: List):
        """Открыть позицию"""
        entry_price = float(kline[4])
        
        position = {
            'symbol': self.symbol,
            'direction': 'LONG' if random.random() > 0.5 else 'SHORT',
            'entry_price': entry_price,
            'entry_time': datetime.fromtimestamp(int(kline[0]) / 1000),
            'quantity': 0.01,
            'tp_percent': 0.06,
            'sl_percent': 0.015
        }
        
        self.trades.append(position)
    
    async def _check_position_exits(self, kline: List):
        """Проверить выходы"""
        close_price = float(kline[4])
        
        trades_to_close = []
        
        for position in self.trades:
            if position['direction'] == "LONG":
                pnl_percent = (close_price - position['entry_price']) / position['entry_price']
            else:
                pnl_percent = (position['entry_price'] - close_price) / position['entry_price']
            
            # Проверить выходы
            if pnl_percent >= position['tp_percent']:
                trades_to_close.append((position, "take_profit", pnl_percent))
            elif pnl_percent <= -position['sl_percent']:
                trades_to_close.append((position, "stop_loss", pnl_percent))
        
        # Закрыть позиции
        for position, reason, pnl_percent in trades_to_close:
            self.closed_trades.append({
                'symbol': position['symbol'],
                'direction': position['direction'],
                'entry_price': position['entry_price'],
                'exit_price': close_price,
                'pnl_percent': pnl_percent,
                'reason': reason
            })
            self.trades.remove(position)
    
    def _calculate_metrics(self) -> BacktestMetrics:
        """Рассчитать метрики"""
        metrics = BacktestMetrics()
        
        metrics.total_trades = len(self.closed_trades)
        metrics.trades = self.closed_trades
        
        if metrics.total_trades == 0:
            return metrics
        
        wins = [t for t in self.closed_trades if t['pnl_percent'] > 0]
        losses = [t for t in self.closed_trades if t['pnl_percent'] <= 0]
        
        metrics.winning_trades = len(wins)
        metrics.losing_trades = len(losses)
        metrics.win_rate = metrics.winning_trades / metrics.total_trades
        
        metrics.gross_profit = sum(t['pnl_percent'] for t in wins) if wins else 0
        metrics.gross_loss = sum(abs(t['pnl_percent']) for t in losses) if losses else 0
        metrics.total_pnl = metrics.gross_profit - metrics.gross_loss
        metrics.profit_factor = metrics.gross_profit / metrics.gross_loss if metrics.gross_loss > 0 else 0
        
        metrics.avg_win = metrics.gross_profit / len(wins) if wins else 0
        metrics.avg_loss = metrics.gross_loss / len(losses) if losses else 0
        metrics.win_loss_ratio = metrics.avg_win / metrics.avg_loss if metrics.avg_loss > 0 else 0
        
        return metrics
    
    def _print_results(self, metrics: BacktestMetrics):
        """Вывести результаты"""
        print(f"\n{'='*80}")
        print(f"📊 РЕЗУЛЬТАТЫ BACKTESTING")
        print(f"{'='*80}\n")
        
        print(f"📈 ОБЩИЕ МЕТРИКИ:")
        print(f"   Всего сделок: {metrics.total_trades}")
        print(f"   Прибыльных: {metrics.winning_trades} ({metrics.win_rate*100:.1f}%)")
        print(f"   Убыточных: {metrics.losing_trades} ({(1-metrics.win_rate)*100:.1f}%)")
        print(f"   Общий PnL: {metrics.total_pnl:.4f}")
        
        print(f"\n💰 ФИНАНСОВЫЕ МЕТРИКИ:")
        print(f"   Gross Profit: {metrics.gross_profit:.4f}")
        print(f"   Gross Loss: {metrics.gross_loss:.4f}")
        print(f"   Profit Factor: {metrics.profit_factor:.2f}")
        print(f"   Avg Win: {metrics.avg_win:.4f}")
        print(f"   Avg Loss: {metrics.avg_loss:.4f}")
        print(f"   Win/Loss Ratio: {metrics.win_loss_ratio:.2f}")
        
        print(f"\n{'='*80}\n")
