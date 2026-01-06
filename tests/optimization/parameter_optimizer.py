"""
Parameter Optimizer для поиска оптимальных параметров торговли
"""
import asyncio
from itertools import product
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from loguru import logger
import json
from pathlib import Path

from tests.backtesting.backtest_engine import BacktestEngine, BacktestMetrics

@dataclass
class OptimizationResult:
    """Результат оптимизации"""
    tp_percent: float
    sl_percent: float
    confidence_min: float
    metrics: BacktestMetrics
    rank: int = 0

class ParameterOptimizer:
    """Оптимизирует параметры через exhaustive search"""
    
    def __init__(self, config, symbol: str = "BTC-USDT"):
        self.config = config
        self.symbol = symbol
        self.results: List[OptimizationResult] = []
    
    async def optimize(
        self,
        start_date: str = "2025-12-01",
        end_date: str = "2026-01-06",
        tp_range: List[float] = None,
        sl_range: List[float] = None,
        confidence_range: List[float] = None,
        verbose: bool = True
    ) -> List[OptimizationResult]:
        """
        Найти оптимальные параметры
        
        Args:
            tp_range: Список значений Take Profit (%)
            sl_range: Список значений Stop Loss (%)
            confidence_range: Список значений мин. confidence
        """
        
        if tp_range is None:
            tp_range = [0.04, 0.06, 0.08, 0.10]  # 4% - 10%
        
        if sl_range is None:
            sl_range = [0.01, 0.015, 0.02, 0.025]  # 1% - 2.5%
        
        if confidence_range is None:
            confidence_range = [0.55, 0.60, 0.65, 0.70]  # 55% - 70%
        
        total_combinations = len(tp_range) * len(sl_range) * len(confidence_range)
        
        if verbose:
            print(f"\n{'='*80}")
            print(f"🔍 PARAMETER OPTIMIZATION")
            print(f"{'='*80}\n")
            print(f"📊 Параметры поиска:")
            print(f"   TP%: {tp_range}")
            print(f"   SL%: {sl_range}")
            print(f"   Confidence: {confidence_range}")
            print(f"   Всего комбинаций: {total_combinations}\n")
        
        idx = 1
        
        for tp, sl, conf in product(tp_range, sl_range, confidence_range):
            if verbose:
                print(f"[{idx}/{total_combinations}] TP={tp:.2%} | SL={sl:.2%} | Conf={conf:.2f}", end=" → ")
            
            try:
                # Создать engine и запустить
                engine = BacktestEngine(self.config, symbol=self.symbol)
                metrics = await engine.run(
                    start_date=start_date,
                    end_date=end_date,
                    verbose=False
                )
                
                # Сохранить результат
                result = OptimizationResult(
                    tp_percent=tp,
                    sl_percent=sl,
                    confidence_min=conf,
                    metrics=metrics
                )
                
                self.results.append(result)
                
                if verbose:
                    print(f"PF={metrics.profit_factor:.2f} | WR={metrics.win_rate:.1%} | PnL={metrics.total_pnl:.4f}")
            
            except Exception as e:
                logger.error(f"❌ Ошибка при TP={tp}, SL={sl}, Conf={conf}: {e}")
                if verbose:
                    print(f"ERROR")
            
            idx += 1
        
        # Отранжировать результаты
        self._rank_results()
        
        if verbose:
            self._print_results()
        
        return self.results
    
    def _rank_results(self):
        """Отранжировать результаты по Profit Factor"""
        sorted_results = sorted(
            self.results,
            key=lambda x: (x.metrics.profit_factor, x.metrics.win_rate),
            reverse=True
        )
        
        for i, result in enumerate(sorted_results, 1):
            result.rank = i
    
    def _print_results(self):
        """Вывести результаты"""
        print(f"\n{'='*80}")
        print(f"🏆 TOP 10 ЛУЧШИХ ПАРАМЕТРОВ")
        print(f"{'='*80}\n")
        
        top_10 = self.results[:10]
        
        print(f"{'Rank':<5} {'TP%':<8} {'SL%':<8} {'Conf':<8} {'PF':<8} {'WR':<8} {'Trades':<8}")
        print(f"{'-'*60}")
        
        for result in top_10:
            print(
                f"{result.rank:<5} "
                f"{result.tp_percent:<8.2%} "
                f"{result.sl_percent:<8.2%} "
                f"{result.confidence_min:<8.2f} "
                f"{result.metrics.profit_factor:<8.2f} "
                f"{result.metrics.win_rate:<8.1%} "
                f"{result.metrics.total_trades:<8}"
            )
        
        best = self.results[0]
        
        print(f"\n{'='*80}")
        print(f"🎯 ЛУЧШИЙ РЕЗУЛЬТАТ:")
        print(f"{'='*80}\n")
        print(f"   TP%: {best.tp_percent:.2%}")
        print(f"   SL%: {best.sl_percent:.2%}")
        print(f"   Confidence: {best.confidence_min:.2f}")
        print(f"   Profit Factor: {best.metrics.profit_factor:.2f}")
        print(f"   Win Rate: {best.metrics.win_rate:.1%}")
        print(f"   Total Trades: {best.metrics.total_trades}")
        print(f"   Total PnL: {best.metrics.total_pnl:.4f}")
        print(f"\n{'='*80}\n")
    
    def save_results(self, filepath: str = "tests/optimization/results/optimization_results.json"):
        """Сохранить результаты в JSON"""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        results_data = []
        for result in self.results:
            results_data.append({
                'rank': result.rank,
                'tp_percent': result.tp_percent,
                'sl_percent': result.sl_percent,
                'confidence_min': result.confidence_min,
                'profit_factor': result.metrics.profit_factor,
                'win_rate': result.metrics.win_rate,
                'total_trades': result.metrics.total_trades,
                'total_pnl': result.metrics.total_pnl,
                'gross_profit': result.metrics.gross_profit,
                'gross_loss': result.metrics.gross_loss
            })
        
        with open(filepath, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"✅ Результаты сохранены: {filepath}")
    
    def get_best_params(self) -> Optional[OptimizationResult]:
        """Получить лучшие параметры"""
        return self.results[0] if self.results else None
