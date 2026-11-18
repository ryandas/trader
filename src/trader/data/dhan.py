from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pandas as pd

BASE = "https://api.dhan.co/v2"
IST = timezone(timedelta(hours=5, minutes=30))


class DhanAuthError(RuntimeError):
    pass


class DhanClient:
    """Minimal client for the daily historical-candles endpoint."""

    def __init__(self, client_id: str, access_token: str, min_interval: float = 0.25):
        self._http = httpx.Client(
            base_url=BASE,
            timeout=30,
            headers={
                "access-token": access_token,
                "client-id": client_id,
                "Content-Type": "application/json",
            },
        )
        self._min_interval = min_interval
        self._last = 0.0

    def _post(self, path: str, body: dict, retries: int = 4) -> dict:
        for attempt in range(retries):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self._http.post(path, json=body)
            if r.status_code in (401, 403):
                raise DhanAuthError(f"Dhan rejected request ({r.status_code}): {r.text[:200]}")
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Dhan request failed after {retries} retries: {path}")

    def daily_candles(
        self,
        security_id: str | int,
        start: date,
        end: date,
        segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
    ) -> pd.DataFrame:
        """Daily OHLCV between start and end (inclusive), indexed by IST date."""
        data = self._post(
            "/charts/historical",
            {
                "securityId": str(security_id),
                "exchangeSegment": segment,
                "instrument": instrument,
                "expiryCode": 0,
                "oi": False,
                "fromDate": start.isoformat(),
                "toDate": end.isoformat(),
            },
        )
        if not data.get("close"):
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        ts = data["timestamp"]
        # Some Dhan responses count seconds from 1980-01-01 instead of 1970.
        offset = 315_532_800 if ts and ts[0] < 631_152_000 else 0
        idx = [datetime.fromtimestamp(t + offset, tz=IST).date() for t in ts]
        df = pd.DataFrame(
            {k: data[k] for k in ("open", "high", "low", "close", "volume")},
            index=pd.DatetimeIndex(idx, name="date"),
        )
        return df[~df.index.duplicated(keep="last")].sort_index()
