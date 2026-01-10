# WS/REST/SSL Investigation (2026-01-10 11-04-01)

Source logs: `C:\Users\krivo\simple trading bot okx\logs\futures\archived\staging_2026-01-10_11-04-01`

## get_current_price / REST callback logging

get_current_price* lines: 6065
REST API callback lines: 5997
Fallback to REST API client lines: 36
Literal get_current_price_callback mentions: 0

Sample REST callback lines:

- 2026-01-10 02:03:12.120 | DEBUG    | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1769 | ⚠️ TSL: Using REST API callback for XRP-USDT: 2.09680000
- 2026-01-10 02:03:21.350 | DEBUG    | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1769 | ⚠️ TSL: Using REST API callback for XRP-USDT: 2.09650000
- 2026-01-10 02:03:31.446 | DEBUG    | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1769 | ⚠️ TSL: Using REST API callback for XRP-USDT: 2.09590000
- 2026-01-10 02:03:42.456 | DEBUG    | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1769 | ⚠️ TSL: Using REST API callback for XRP-USDT: 2.09620000
- 2026-01-10 02:03:52.921 | DEBUG    | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1769 | ⚠️ TSL: Using REST API callback for XRP-USDT: 2.09680000

Sample REST fallback lines:

- 2026-01-10 02:31:13.724 | WARNING  | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1788 | 🔴 TSL: Falling back to REST API client for BTC-USDT
- 2026-01-10 03:04:17.829 | WARNING  | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1788 | 🔴 TSL: Falling back to REST API client for BTC-USDT
- 2026-01-10 03:43:22.055 | WARNING  | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1788 | 🔴 TSL: Falling back to REST API client for XRP-USDT
- 2026-01-10 03:50:53.238 | WARNING  | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1788 | 🔴 TSL: Falling back to REST API client for ETH-USDT
- 2026-01-10 03:56:54.030 | WARNING  | src.strategies.scalping.futures.coordinators.trailing_sl_coordinator:_get_current_price:1788 | 🔴 TSL: Falling back to REST API client for ETH-USDT

## price=0 timeline (from debug tsl_check)

Total price=0 events: 33602
First: 2026-01-10 02:22:39.016000
Last:  2026-01-10 11:03:41.375000

Per-symbol counts:

| Symbol | price=0 count | Sample timestamps |
| --- | ---: | --- |
| BTC | 7640 | 2026-01-10 02:22:39, 2026-01-10 02:22:39, 2026-01-10 02:22:44, 2026-01-10 02:22:48, 2026-01-10 02:22:49 |
| DOGE | 5414 | 2026-01-10 03:22:40, 2026-01-10 03:22:45, 2026-01-10 03:22:50, 2026-01-10 03:22:55, 2026-01-10 03:22:58 |
| ETH | 7548 | 2026-01-10 02:28:02, 2026-01-10 02:28:07, 2026-01-10 02:28:12, 2026-01-10 02:28:12, 2026-01-10 02:28:17 |
| SOL | 6138 | 2026-01-10 03:58:17, 2026-01-10 03:58:22, 2026-01-10 03:58:22, 2026-01-10 03:58:27, 2026-01-10 03:58:32 |
| XRP | 6862 | 2026-01-10 03:09:47, 2026-01-10 03:09:48, 2026-01-10 03:09:53, 2026-01-10 03:09:58, 2026-01-10 03:10:03 |

## SSL errors timeline

Total SSL errors: 110
First: 2026-01-10 02:02:39.168000
Last:  2026-01-10 10:57:48.916000

Sample SSL error timestamps:

- 2026-01-10 02:02:39.168000
- 2026-01-10 02:07:10.466000
- 2026-01-10 02:07:10.467000
- 2026-01-10 02:23:42.820000
- 2026-01-10 03:02:47.849000
- 2026-01-10 03:13:19.238000
- 2026-01-10 03:13:19.239000
- 2026-01-10 03:14:49.237000
- 2026-01-10 03:14:49.238000
- 2026-01-10 03:14:49.265000

## Correlation (SSL ? price=0)

SSL errors with price=0 within ?10s: 107 / 110