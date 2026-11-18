from __future__ import annotations

import io

import httpx
import pandas as pd
from sqlalchemy import text

from .. import db

NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
MIN_ROWS = 400
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _get(url: str) -> pd.DataFrame:
    r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), low_memory=False)


def build_instruments() -> pd.DataFrame:
    """NIFTY 500 constituents joined to Dhan securityIds. Stored in the `instruments` table."""
    n500 = _get(NIFTY500_URL)[["Symbol", "Company Name", "Industry"]]
    n500.columns = ["symbol", "name", "sector"]
    sm = _get(SCRIP_MASTER_URL)
    eq = sm[
        (sm["SEM_EXM_EXCH_ID"] == "NSE")
        & (sm["SEM_SEGMENT"] == "E")
        & (sm["SEM_SERIES"] == "EQ")
    ][["SEM_TRADING_SYMBOL", "SEM_SMST_SECURITY_ID"]]
    eq.columns = ["symbol", "security_id"]
    out = n500.merge(eq, on="symbol", how="left")
    dups = int(out["symbol"].duplicated().sum())
    if dups:
        print(f"warning: {dups} duplicate symbol rows dropped (kept first)")
        out = out.drop_duplicates("symbol", keep="first")
    missing = out[out["security_id"].isna()]["symbol"].tolist()
    if missing:
        print(f"warning: {len(missing)} symbols without a Dhan securityId: {missing[:10]}")
    out = out.dropna(subset=["security_id"])
    out["security_id"] = out["security_id"].astype(int)
    if len(out) < MIN_ROWS:
        raise ValueError(f"only {len(out)} instruments (< {MIN_ROWS}); refusing to overwrite the instruments table")
    save_instruments(out)
    return out


def save_instruments(df: pd.DataFrame) -> None:
    """Replace the whole instrument list in one transaction."""
    rows = [{"o": k, "s": r.symbol, "n": r.name, "c": r.sector, "i": int(r.security_id)} for k, r in enumerate(df.itertuples())]
    with db.engine().begin() as c:
        c.execute(text("DELETE FROM instruments"))
        c.execute(text("INSERT INTO instruments (ord, symbol, name, sector, security_id) VALUES (:o, :s, :n, :c, :i)"), rows)


def load_instruments() -> pd.DataFrame:
    df = db.qdf("SELECT symbol, name, sector, security_id FROM instruments ORDER BY ord")
    if df.empty:
        raise SystemExit("Run `trader init` first to build the instrument list.")
    return df
