from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

import pandas as pd

from .dhan import DhanClient

COLS = ["open", "high", "low", "close", "volume"]
BENCHMARK = "NIFTY500"
ALIASES = {BENCHMARK: "^CRSLDX"}  # index tickers are used as-is, not suffixed with .NS


class CandleSource(Protocol):
    def daily_candles(
        self, symbol: str, security_id: str | int, start: date, end: date
    ) -> pd.DataFrame: ...


class YFinanceSource:
    """Daily NSE candles from Yahoo. Close is split-adjusted but not dividend-adjusted,
    so previously stored bars stay valid when new bars are appended."""

    max_span_days = 20_000  # one request covers any range

    def daily_candles(self, symbol, security_id, start, end) -> pd.DataFrame:
        import yfinance as yf

        ticker = ALIASES.get(symbol, f"{symbol}.NS")
        df = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
        if df.empty:
            return pd.DataFrame(columns=COLS)
        df = df.rename(columns=str.lower)[COLS]
        df.index = pd.DatetimeIndex(df.index.tz_localize(None).normalize(), name="date")
        df = df.dropna(subset=["close"])
        if symbol not in ALIASES:  # indices report zero volume
            df = df[df["volume"] > 0]  # drop holiday/no-trade rows
        return df[~df.index.duplicated(keep="last")].sort_index()


class DhanSource:
    """Requires the paid Data APIs plan."""

    def __init__(self, client: DhanClient):
        self.client = client

    def daily_candles(self, symbol, security_id, start, end) -> pd.DataFrame:
        return self.client.daily_candles(security_id, start, end)
