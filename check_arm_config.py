#!/usr/bin/env python3
"""
  ARM -      
"""
import yaml

def check_arm_config():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    adaptive_regime = config['scalping']['adaptive_regime']

    print('  ARM :')
    print('=' * 60)

    #   
    for regime_name in ['trending', 'ranging', 'choppy']:
        print(f'\n: {regime_name.upper()}')
        print('-' * 40)
        
        if regime_name not in adaptive_regime:
            print(f' {regime_name}  !')
            continue
        
        regime = adaptive_regime[regime_name]
        
        #  
        basic_params = ['min_score_threshold', 'max_trades_per_hour', 'position_size_multiplier', 
                       'tp_atr_multiplier', 'sl_atr_multiplier', 'cooldown_after_loss_minutes',
                       'pivot_bonus_multiplier', 'volume_profile_bonus_multiplier']
        
        print('OK  :')
        for param in basic_params:
            if param in regime:
                print(f'  OK {param}: {regime[param]}')
            else:
                print(f'  ERROR {param}: ')
        
        # 
        if 'indicators' in regime:
            print(' :')
            indicators = regime['indicators']
            indicator_params = ['rsi_overbought', 'rsi_oversold', 'volume_threshold', 
                              'sma_fast', 'sma_slow', 'atr_period']
            for param in indicator_params:
                if param in indicators:
                    print(f'   {param}: {indicators[param]}')
                else:
                    print(f'   {param}: ')
        else:
            print('  indicators ')
        
        # 
        if 'modules' in regime:
            print(' :')
            modules = regime['modules']
            
            # Multi-Timeframe
            if 'multi_timeframe' in modules:
                mtf = modules['multi_timeframe']
                print('   multi_timeframe:')
                for param in ['block_opposite', 'score_bonus', 'confirmation_timeframe']:
                    if param in mtf:
                        print(f'     {param}: {mtf[param]}')
                    else:
                        print(f'     {param}: ')
            else:
                print('   multi_timeframe ')
            
            # Correlation Filter
            if 'correlation_filter' in modules:
                corr = modules['correlation_filter']
                print('   correlation_filter:')
                for param in ['correlation_threshold', 'max_correlated_positions', 'block_same_direction_only']:
                    if param in corr:
                        print(f'     {param}: {corr[param]}')
                    else:
                        print(f'     {param}: ')
            else:
                print('   correlation_filter ')
            
            # Time Filter
            if 'time_filter' in modules:
                time_f = modules['time_filter']
                print('   time_filter:')
                for param in ['prefer_overlaps', 'avoid_low_liquidity_hours', 'avoid_weekends']:
                    if param in time_f:
                        print(f'     {param}: {time_f[param]}')
                    else:
                        print(f'     {param}: ')
            else:
                print('   time_filter ')
            
            # Pivot Points
            if 'pivot_points' in modules:
                pivot = modules['pivot_points']
                print('   pivot_points:')
                for param in ['level_tolerance_percent', 'score_bonus_near_level', 'use_last_n_days']:
                    if param in pivot:
                        print(f'     {param}: {pivot[param]}')
                    else:
                        print(f'     {param}: ')
            else:
                print('   pivot_points ')
            
            # Volume Profile
            if 'volume_profile' in modules:
                vp = modules['volume_profile']
                print('   volume_profile:')
                for param in ['score_bonus_in_value_area', 'score_bonus_near_poc', 'poc_tolerance_percent', 'lookback_candles']:
                    if param in vp:
                        print(f'     {param}: {vp[param]}')
                    else:
                        print(f'     {param}: ')
            else:
                print('   volume_profile ')
        else:
            print('  modules ')

    print('\n' + '=' * 60)
    print('  ')

if __name__ == "__main__":
    check_arm_config()
