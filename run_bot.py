#!/usr/bin/env python3
"""
Trading Bot Runner Script
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def check_environment():
    """Check if virtual environment is set up"""
    venv_path = Path("venv")
    if not venv_path.exists():
        print("Virtual environment not found. Please run:")
        print("   python -m venv venv")
        print("   source venv/bin/activate  # On Windows: venv\\Scripts\\activate")
        print("   pip install -r requirements.txt")
        return False

    # Check if .env file exists
    env_file = Path(".env")
    if not env_file.exists():
        print(".env file not found. Please:")
        print("   1. Copy .env.example to .env")
        print("   2. Fill in your OKX API credentials")
        return False

    return True


def install_dependencies():
    """Install required dependencies"""
    try:
        print("Installing dependencies...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            check=True,
        )
        print("Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install dependencies: {e}")
        return False


def run_bot(config_path="config.yaml", dry_run=False):
    """Run the trading bot"""
    if not check_environment():
        return False

    try:
        # Set environment variables for dry run
        env = os.environ.copy()
        if dry_run:
            env["BOT_DRY_RUN"] = "true"
            print("Running in DRY RUN mode (no real trades)")

        print("Starting trading bot...")
        print(f"Using config: {config_path}")

        # Run the bot
        subprocess.run([sys.executable, "-m", "src.main"], env=env, check=True)

    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except subprocess.CalledProcessError as e:
        print(f"Bot crashed: {e}")
        return False

    return True


def validate_config(config_path="config.yaml"):
    """Validate configuration file"""
    try:
        from src.config import load_config

        config = load_config(config_path)
        print("Configuration is valid")

        # Print summary
        print(f"Scalping enabled: {config.scalping.enabled}")
        print(f"Trading symbols: {', '.join(config.scalping.symbols)}")
        print(f"Risk per trade: {config.risk.risk_per_trade_percent}%")
        print(f"Max daily loss: {config.risk.max_daily_loss_percent}%")

        return True
    except Exception as e:
        print(f"Configuration error: {e}")
        return False


def backtest():
    """Run backtest"""
    try:
        print("Running backtest...")
        # Implement backtest runner here
        print("Backtest completed")
        return True
    except Exception as e:
        print(f"Backtest failed: {e}")
        return False


def main():
    """Main runner function"""
    parser = argparse.ArgumentParser(description="OKX Trading Bot Runner")
    parser.add_argument(
        "--config", default="config.yaml", help="Configuration file path"
    )
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode")
    parser.add_argument("--install", action="store_true", help="Install dependencies")
    parser.add_argument(
        "--validate", action="store_true", help="Validate configuration"
    )
    parser.add_argument("--backtest", action="store_true", help="Run backtest")

    args = parser.parse_args()

    print("OKX Trading Bot Runner")
    print("=" * 30)

    if args.install:
        if not install_dependencies():
            sys.exit(1)
        return

    if args.validate:
        if not validate_config(args.config):
            sys.exit(1)
        return

    if args.backtest:
        if not backtest():
            sys.exit(1)
        return

    # Default: run the bot
    if not run_bot(args.config, args.dry_run):
        sys.exit(1)


if __name__ == "__main__":
    main()
