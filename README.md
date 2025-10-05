\# OKX Trading Bot 🤖



Advanced algorithmic trading bot for OKX exchange with scalping and trend-following strategies.



\## ✨ Features



\- \*\*Scalping Strategy\*\*: High-frequency trading with multiple technical indicators

\- \*\*Risk Management\*\*: Comprehensive risk controls and position sizing

\- \*\*Real-time Monitoring\*\*: WebSocket-based market data streaming

\- \*\*Technical Indicators\*\*: SMA, EMA, RSI, ATR, Bollinger Bands, Volume analysis

\- \*\*Async Architecture\*\*: High-performance asynchronous execution

\- \*\*Comprehensive Log# OKX Trading Bot 🤖



Advanced algorithmic trading bot for OKX exchange with scalping and trend-following strategies.



\## ✨ Features



\- \*\*Scalping Strategy\*\*: High-frequency trading with multiple technical indicators

\- \*\*Risk Management\*\*: Comprehensive risk controls and position sizing

\- \*\*Real-time Monitoring\*\*: WebSocket-based market data streaming

\- \*\*Technical Indicators\*\*: SMA, EMA, RSI, ATR, Bollinger Bands, Volume analysis

\- \*\*Async Architecture\*\*: High-performance asynchronous execution

\- \*\*Comprehensive Logging\*\*: Detailed trade and system logs

\- \*\*Health Monitoring\*\*: API health checks and automatic reconnection



\## 🔧 Technical Indicators



\### Scalping Strategy Indicators:

\- \*\*Moving Averages\*\*: SMA (5, 20) and EMA (8, 21) for trend detection

\- \*\*RSI\*\*: Momentum oscillator with overbought/oversold levels

\- \*\*ATR\*\*: Volatility measurement for dynamic stop-loss and take-profit

\- \*\*Bollinger Bands\*\*: Price envelope for mean reversion signals

\- \*\*Volume Analysis\*\*: Volume spike detection for confirmation



\### Entry Conditions:

\- Multiple indicator confluence required

\- Minimum volatility threshold (ATR-based)

\- Volume confirmation

\- Risk-reward ratio validation



\### Exit Conditions:

\- Dynamic ATR-based stop-loss and take-profit

\- Maximum holding time limits

\- Risk management overrides



\## 🚀 Quick Start



\### 1. Setup Environment



```bash

\# Clone the repository

git clone <repository-url>

cd okx-trading-bot



\# Create virtual environment

python -m venv venv



\# Activate virtual environment

\# On Windows:

venv\\\\Scripts\\\\activate

\# On Linux/Mac:

source venv/bin/activate



\# Install dependencies

pip install -r requirements.txt

```



\### 2. Configuration



```bash

\# Copy environment template

cp .env.example .env



\# Edit .env with your OKX API credentials

\# Get API keys from: https://www.okx.com/account/my-api

```



\#### .env file:

```env

OKX\_API\_KEY=your\_api\_key\_here

OKX\_API\_SECRET=your\_api\_secret\_here

OKX\_PASSPHRASE=your\_passphrase\_here

```



\### 3. Configure Trading Parameters



Edit `config.yaml` to adjust:

\- Trading symbols

\- Risk parameters

\- Strategy settings

\- Indicator parameters



\### 4. Run the Bot



```bash

\# Validate configuration

python run\_bot.py --validate



\# Run in sandbox mode (recommended first)

python run\_bot.py --dry-run



\# Run live trading

python run\_bot.py

```



\## 📊 Configuration



\### Risk Management Settings



```yaml

risk:

&nbsp; max\_position\_size\_percent: 5.0    # Max 5% of balance per position

&nbsp; max\_daily\_loss\_percent: 10.0      # Stop trading at 10% daily loss

&nbsp; risk\_per\_trade\_percent: 1.0       # Risk 1% per trade

&nbsp; max\_open\_positions: 3             # Maximum concurrent positions

```



\### Scalping Strategy Settings



```yaml

scalping:

&nbsp; enabled: true

&nbsp; symbols: \["BTC-USDT", "ETH-USDT"]

&nbsp; timeframe: "1m"

&nbsp; max\_trades\_per\_hour: 10

&nbsp; cooldown\_after\_loss\_minutes: 5

&nbsp; 

&nbsp; entry:

&nbsp;   min\_volatility\_atr: 0.0005

&nbsp;   rsi\_overbought: 70

&nbsp;   rsi\_oversold: 30

&nbsp;   volume\_threshold: 1.2

&nbsp; 

&nbsp; exit:

&nbsp;   take\_profit\_atr\_multiplier: 2.0

&nbsp;   stop\_loss\_atr\_multiplier: 1.5

&nbsp;   max\_holding\_minutes: 15

```



\## 🛡️ Risk Management



\### Built-in Safety Features:

\- \*\*Position Sizing\*\*: Kelly criterion-based sizing with ATR

\- \*\*Daily Loss Limits\*\*: Automatic shutdown at loss threshold

\- \*\*Maximum Positions\*\*: Limit concurrent trades

\- \*\*Exposure Control\*\*: Maximum portfolio exposure limits

\- \*\*Emergency Stop\*\*: Manual and automatic position closure



\### Risk Metrics Monitoring:

\- Real-time P\&L tracking

\- Drawdown monitoring

\- Win rate analysis

\- Exposure ratio tracking



\## 📈 Performance Monitoring



\### Logging:

\- `logs/trading\_bot\_YYYY-MM-DD.log`: General bot activity

\- `logs/errors\_YYYY-MM-DD.log`: Error-specific logs

\- Real-time console output with trade notifications



\### Key Metrics:

\- Total trades executed

\- Win/loss ratio

\- Daily P\&L

\- Maximum drawdown

\- Active positions

\- Risk metrics



\## 🔄 Strategy Details



\### Scalping Strategy Logic:



1\. \*\*Market Data\*\*: Real-time tick data via WebSocket

2\. \*\*Indicator Calculation\*\*: Multi-timeframe technical analysis

3\. \*\*Signal Generation\*\*: Confluence-based entry signals

4\. \*\*Position Management\*\*: Dynamic exits with ATR-based levels

5\. \*\*Risk Control\*\*: Pre-trade and post-trade risk checks



\### Entry Signal Requirements:

\- Price momentum confirmation (MA alignment)

\- Volatility threshold met (ATR minimum)

\- Volume confirmation (above average)

\- RSI in tradeable range

\- Bollinger Band positioning



\### Exit Triggers:

\- Take profit hit (ATR-based)

\- Stop loss hit (ATR-based)

\- Maximum holding time reached

\- Risk limits exceeded



\## 🚨 Important Notes



\### Before Live Trading:

1\. \*\*Test thoroughly in sandbox mode\*\*

2\. \*\*Start with small amounts\*\*

3\. \*\*Monitor performance closely\*\*

4\. \*\*Understand all risk parameters\*\*

5\. \*\*Have exit plan ready\*\*



\### API Requirements:

\- OKX account with API access enabled

\- Sufficient balance for trading

\- API keys with trading permissions

\- Stable internet connection



\## 🐛 Troubleshooting



\### Common Issues:



1\. \*\*API Connection Failed\*\*

&nbsp;  - Check API credentials in .env

&nbsp;  - Verify API permissions on OKX

&nbsp;  - Check internet connection



2\. \*\*"No files to check" in pre-commit\*\*

&nbsp;  - Files need to be added to git: `git add .`

&nbsp;  - Run: `pre-commit run --files filename.py`



3\. \*\*Import Errors\*\*

&nbsp;  - Ensure virtual environment is activated

&nbsp;  - Run: `pip install -r requirements.txt`



4\. \*\*WebSocket Disconnection\*\*

&nbsp;  - Bot automatically reconnects

&nbsp;  - Check logs for connection issues



\## 📞 Support



For issues and questions:

1\. Check troubleshooting section

2\. Review logs in `logs/` directory

3\. Validate configuration with `python run\_bot.py --validate`



\## ⚖️ Disclaimer



\*\*This bot is for educational and research purposes. Trading cryptocurrencies involves significant risk. Never trade more than you can afford to lose. The authors are not responsible for any financial losses.\*\*



\### Legal Notes:

\- Ensure compliance with local regulations

\- Understand tax implications of automated trading

\- Review exchange terms of service

\- Consider professional financial advice



\## 📄 License



This project is licensed under the MIT License - see the LICENSE file for details.ging\*\*: Detailed trade and system logs

\- \*\*Health Monitoring\*\*: API health checks and automatic reconnection



\## 🔧 Technical Indicators



\### Scalping Strategy Indicators:

\- \*\*Moving Averages\*\*: SMA (5, 20) and EMA (8, 21) for trend detection

\- \*\*RSI\*\*: Momentum oscillator with overbought/oversold levels

\- \*\*ATR\*\*: Volatility measurement for dynamic stop-loss and take-profit

\- \*\*Bollinger Bands\*\*: Price envelope for mean reversion signals

\- \*\*Volume Analysis\*\*: Volume spike detection for confirmation



\### Entry Conditions:

\- Multiple indicator confluence required

\- Minimum volatility threshold (ATR-based)

\- Volume confirmation

\- Risk-reward ratio validation



\### Exit Conditions:

\- Dynamic ATR-based stop-loss and take-profit

\- Maximum holding time limits

\- Risk management overrides



\## 🚀 Quick Start



\### 1. Setup Environment



```bash

\# Clone the repository

git clone <repository-url>

cd okx-trading-bot



\# Create virtual environment

python -m venv venv



\# Activate virtual environment

\# On Windows:

venv\\\\Scripts\\\\activate

\# On Linux/Mac:

source venv/bin/activate



\# Install dependencies

pip install -r requirements.txt

```



\### 2. Configuration



```bash

\# Copy environment template

cp .env.example .env



\# Edit .env with your OKX API credentials

\# Get API keys from: https://www.okx.com/account/my-api

```



\#### .env file:

```env

OKX\_API\_KEY=your\_api\_key\_here

OKX\_API\_SECRET=your\_api\_secret\_here

OKX\_PASSPHRASE=your\_passphrase\_here

```



\### 3. Configure Trading Parameters



Edit `config.yaml` to adjust:

\- Trading symbols

\- Risk parameters

\- Strategy settings

\- Indicator parameters



\### 4. Run the Bot



```bash

\# Validate configuration

python run\_bot.py --validate



\# Run in sandbox mode (recommended first)

python run\_bot.py --dry-run



\# Run live trading

python run\_bot.py

```



\## 📊 Configuration



\### Risk Management Settings



```yaml

risk:

&nbsp; max\_position\_size\_percent: 5.0    # Max 5% of balance per position

&nbsp; max\_daily\_loss\_percent: 10.0      # Stop trading at 10% daily loss

&nbsp; risk\_per\_trade\_percent: 1.0       # Risk 1% per trade

&nbsp; max\_open\_positions: 3             # Maximum concurrent positions

```



\### Scalping Strategy Settings



```yaml

scalping:

&nbsp; enabled: true

&nbsp; symbols: \["BTC-USDT", "ETH-USDT"]

&nbsp; timeframe: "1m"

&nbsp; max\_trades\_per\_hour: 10

&nbsp; cooldown\_after\_loss\_minutes: 5

&nbsp; 

&nbsp; entry:

&nbsp;   min\_volatility\_atr: 0.0005

&nbsp;   rsi\_overbought: 70

&nbsp;   rsi\_oversold: 30

&nbsp;   volume\_threshold: 1.2

&nbsp; 

&nbsp; exit:

&nbsp;   take\_profit\_atr\_multiplier: 2.0

&nbsp;   stop\_loss\_atr\_multiplier: 1.5

&nbsp;   max\_holding\_minutes: 15

```



\## 🛡️ Risk Management



\### Built-in Safety Features:

\- \*\*Position Sizing\*\*: Kelly criterion-based sizing with ATR

\- \*\*Daily Loss Limits\*\*: Automatic shutdown at loss threshold

\- \*\*Maximum Positions\*\*: Limit concurrent trades

\- \*\*Exposure Control\*\*: Maximum portfolio exposure limits

\- \*\*Emergency Stop\*\*: Manual and automatic position closure



\### Risk Metrics Monitoring:

\- Real-time P\&L tracking

\- Drawdown monitoring

\- Win rate analysis

\- Exposure ratio tracking



\## 📈 Performance Monitoring



\### Logging:

\- `logs/trading\_bot\_YYYY-MM-DD.log`: General bot activity

\- `logs/errors\_YYYY-MM-DD.log`: Error-specific logs

\- Real-time console output with trade notifications



\### Key Metrics:

\- Total trades executed

\- Win/loss ratio

\- Daily P\&L

\- Maximum drawdown

\- Active positions

\- Risk metrics



\## 🔄 Strategy Details



\### Scalping Strategy Logic:



1\. \*\*Market Data\*\*: Real-time tick data via WebSocket

2\. \*\*Indicator Calculation\*\*: Multi-timeframe technical analysis

3\. \*\*Signal Generation\*\*: Confluence-based entry signals

4\. \*\*Position Management\*\*: Dynamic exits with ATR-based levels

5\. \*\*Risk Control\*\*: Pre-trade and post-trade risk checks



\### Entry Signal Requirements:

\- Price momentum confirmation (MA alignment)

\- Volatility threshold met (ATR minimum)

\- Volume confirmation (above average)

\- RSI in tradeable range

\- Bollinger Band positioning



\### Exit Triggers:

\- Take profit hit (ATR-based)

\- Stop loss hit (ATR-based)

\- Maximum holding time reached

\- Risk limits exceeded



\## 🚨 Important Notes



\### Before Live Trading:

1\. \*\*Test thoroughly in sandbox mode\*\*

2\. \*\*Start with small amounts\*\*

3\. \*\*Monitor performance closely\*\*

4\. \*\*Understand all risk parameters\*\*

5\. \*\*Have exit plan ready\*\*



\### API Requirements:

\- OKX account with API access enabled

\- Sufficient balance for trading

\- API keys with trading permissions

\- Stable internet connection



\## 🐛 Troubleshooting



\### Common Issues:



1\. \*\*API Connection Failed\*\*

&nbsp;  - Check API credentials in .env

&nbsp;  - Verify API permissions on OKX

&nbsp;  - Check internet connection



2\. \*\*"No files to check" in pre-commit\*\*

&nbsp;  - Files need to be added to git: `git add .`

&nbsp;  - Run: `pre-commit run --files filename.py`



3\. \*\*Import Errors\*\*

&nbsp;  - Ensure virtual environment is activated

&nbsp;  - Run: `pip install -r requirements.txt`



4\. \*\*WebSocket Disconnection\*\*

&nbsp;  - Bot automatically reconnects

&nbsp;  - Check logs for connection issues



\## 📞 Support



For issues and questions:

1\. Check troubleshooting section

2\. Review logs in `logs/` directory

3\. Validate configuration with `python run\_bot.py --validate`



\## ⚖️ Disclaimer



\*\*This bot is for educational and research purposes. Trading cryptocurrencies involves significant risk. Never trade more than you can afford to lose. The authors are not responsible for any financial losses.\*\*



\### Legal Notes:

\- Ensure compliance with local regulations

\- Understand tax implications of automated trading

\- Review exchange terms of service

\- Consider professional financial advice



\## 📄 License



This project is licensed under the MIT License - see the LICENSE file for details.

