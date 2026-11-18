from __future__ import annotations

import typer

from .config import dhan_credentials, load_config
from .data.sources import BENCHMARK, DhanSource, YFinanceSource
from .data import instruments as inst
from .data import store
from .data.dhan import DhanAuthError, DhanClient

app = typer.Typer(no_args_is_help=True, help="Systematic daily swing trader (NIFTY 500 / Dhan)")


@app.command()
def init() -> None:
    """Build the NIFTY 500 -> Dhan securityId instrument list."""
    cfg = load_config()
    df = inst.build_instruments(cfg.data_dir)
    typer.echo(f"{len(df)} instruments written to {cfg.data_dir / 'instruments.csv'}")


@app.command()
def update(
    symbols: list[str] = typer.Argument(None, help="Limit to these symbols (default: all)"),
    source: str = typer.Option("yfinance", help="yfinance (free) or dhan (needs Data APIs plan)"),
) -> None:
    """Backfill / incrementally update daily candles."""
    cfg = load_config()
    df = inst.load_instruments(cfg.data_dir)
    if symbols:
        df = df[df["symbol"].isin(symbols)]
    if source == "dhan":
        cid, tok = dhan_credentials()
        src = DhanSource(DhanClient(cid, tok))
    else:
        src = YFinanceSource()
    total = 0
    if not symbols:  # refresh the benchmark index alongside the full universe
        store.update_symbol(src, cfg.candles_dir, BENCHMARK, 0, cfg.history_years)
    from . import sessions

    target = sessions.last_session_on_or_before(store.last_complete_day())
    not_updated: list[str] = []
    for i, row in enumerate(df.itertuples(), 1):
        try:
            n = store.update_symbol(
                src, cfg.candles_dir, row.symbol, row.security_id, cfg.history_years
            )
        except DhanAuthError as e:
            raise SystemExit(str(e))
        except Exception as e:  # one bad symbol must not abort the whole refresh
            typer.echo(f"[{i}/{len(df)}] {row.symbol}: ERROR {type(e).__name__}: {e}")
            not_updated.append(row.symbol)
            continue
        total += n
        typer.echo(f"[{i}/{len(df)}] {row.symbol}: +{n}")
        if n == 0:
            have = store.load(cfg.candles_dir, row.symbol)
            if have is None or not len(have) or have.index.max().date() < target:
                not_updated.append(row.symbol)
    if not_updated:
        typer.echo(f"WARNING: {len(not_updated)} symbols not updated: {', '.join(not_updated[:10])}")
    typer.echo(f"done, {total} new rows")


@app.command()
def backtest(
    strategy: str = typer.Option("all", help="all, or one of: trend_pullback, breakout, mean_reversion"),
    from_: str = typer.Option("2022-01-01", "--from", help="Backtest start date"),
    to: str = typer.Option(None, help="Backtest end date (default: last bar)"),
    out: str = typer.Option("reports/backtest", help="Output directory for trades/equity CSVs"),
    filters: bool = typer.Option(True, help="Top-N universe + regime/selector rules (off = step-3 baseline)"),
) -> None:
    """Run the portfolio backtest over stored daily candles."""
    import json
    from pathlib import Path

    import pandas as pd

    from . import backtest as bt
    from .config import ROOT
    from .metrics import summarize
    from .strategies import ALL

    cfg = load_config()
    names = list(ALL) if strategy == "all" else [strategy]
    strats = {n: ALL[n]() for n in names}
    prep = bt.prepare(cfg, inst.load_instruments(cfg.data_dir), list(strats.values()), filters)
    res = bt.run(cfg, prep, strats, pd.Timestamp(from_), pd.Timestamp(to) if to else None)
    outdir = ROOT / out
    outdir.mkdir(parents=True, exist_ok=True)
    res.trades.to_csv(outdir / "trades.csv", index=False)
    res.equity.to_csv(outdir / "equity.csv")
    m = summarize(res.equity, res.trades, bt.load_benchmark(cfg))
    typer.echo(json.dumps(m, indent=2))
    if len(res.trades):
        typer.echo("\nPer strategy:")
        typer.echo(res.trades.groupby("strategy").agg(
            trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum"),
            win_rate=("net_pnl", lambda s: round((s > 0).mean() * 100, 1)),
            expR=("r_multiple", "mean")).round(2).to_string())
    typer.echo("\nCaveat: universe = today's NIFTY 500 constituents (survivorship bias).")


@app.command()
def walkforward(
    out: str = typer.Option("reports/walkforward", help="Output directory"),
) -> None:
    """Rolling walk-forward (3y in-sample / 1y out-of-sample); saves fitted params and selector."""
    import json

    from . import backtest as bt
    from . import walkforward as wf
    from .config import ROOT
    from .metrics import summarize

    cfg = load_config()
    instruments = inst.load_instruments(cfg.data_dir)
    grid = wf.build_grid()
    prep = bt.prepare(cfg, instruments, list(grid.values()), filters=True)
    base_prep = bt.prepare(cfg, instruments, [g for k, g in grid.items() if k.endswith("#0")], filters=False)
    res = wf.walk_forward(cfg, prep, base_prep, grid)
    bench = bt.load_benchmark(cfg)
    outdir = ROOT / out
    outdir.mkdir(parents=True, exist_ok=True)
    res.folds.to_csv(outdir / "folds.csv", index=False)
    res.trades.to_csv(outdir / "oos_trades.csv", index=False)
    res.equity.to_csv(outdir / "oos_equity.csv")
    for label, eq, tr in (("WALK-FORWARD (out-of-sample)", res.equity, res.trades),
                          ("BASELINE (no filters, default params)", res.baseline_equity, res.baseline_trades)):
        typer.echo(f"\n== {label} ==")
        typer.echo(json.dumps(summarize(eq, tr, bench), indent=2))
    if len(res.trades):
        typer.echo("\nOOS per strategy:")
        typer.echo(res.trades.groupby("strategy").agg(
            trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum"),
            win_rate=("net_pnl", lambda s: round((s > 0).mean() * 100, 1)),
            expR=("net_pnl", lambda s: round(s.sum() / res.trades.loc[s.index, "risk"].sum(), 3))
        ).round(2).to_string())
    # Final fit on the most recent 3 years: parameters + selector used for live/paper trading.
    last = prep.dates[-1]
    chosen, sel, _ = wf.fit(cfg, prep, grid, last - __import__("pandas").DateOffset(years=3), last)
    (cfg.data_dir / "params.json").write_text(json.dumps(
        {n: {"key": k, "params": grid[k].params} for n, k in chosen.items()}, indent=2))
    sel.save(cfg.data_dir / "selector_stats.json")
    typer.echo(f"\nFitted on last 3y -> {cfg.data_dir / 'params.json'}, selector_stats.json")
    typer.echo("Caveat: universe = today's NIFTY 500 constituents (survivorship bias).")


@app.command("paper-init")
def paper_init(
    start: str = typer.Option(None, help="Ledger start date (default: latest bar, i.e. forward-only)"),
    reset: bool = typer.Option(False, help="Discard an existing ledger and start over"),
) -> None:
    """Start a paper-trading ledger, freezing the fitted params and selector stats."""
    import pandas as pd

    from . import paper
    from .data.sources import BENCHMARK

    cfg = load_config()
    if start is None:
        bench = store.load(cfg.candles_dir, BENCHMARK)
        start = str(bench.index.max().date())
    meta = paper.init(cfg, pd.Timestamp(start), reset)
    typer.echo(f"Paper ledger started at {meta['start']} with capital {meta['capital']:,.0f}.")
    typer.echo(f"Frozen strategies: {', '.join(v['key'] for v in meta['params'].values())}")


@app.command("paper-drop-swing")
def paper_drop_swing() -> None:
    """Remove the swing sleeve from the paper ledger (the momentum sleeve is kept)."""
    from . import paper

    paper.drop_swing(load_config())
    typer.echo("Swing sleeve removed. Re-add it any time with `trader paper-init`.")


@app.command("paper-momentum")
def paper_momentum(
    start: str = typer.Option(None, help="Sleeve start date (default: latest bar, i.e. forward-only)"),
    liquid_top: int = typer.Option(None, help="Only the N most liquid names each day"),
    reset: bool = typer.Option(False, help="Discard an existing momentum sleeve and start over"),
) -> None:
    """Add a momentum-rotation sleeve to the paper ledger (params from config.yaml, then frozen)."""
    import pandas as pd

    from . import momentum as mom
    from . import paper
    from .data.sources import BENCHMARK

    cfg = load_config()
    c = cfg.momentum
    p = mom.MomParams(c.lookback, c.skip, c.top_n, c.buffer, c.bear_exit)
    if start is None:
        start = str(store.load(cfg.candles_dir, BENCHMARK).index.max().date())
    mm = paper.init_momentum(cfg, pd.Timestamp(start), p, liquid_top, reset)
    typer.echo(f"Momentum sleeve started {mm['start']} with capital {mm['capital']:,.0f} + {mm['contribution']:,.0f} each month-end: {p.label()}"
               + (f", liquid top {liquid_top}" if liquid_top else ""))


@app.command()
def daily(
    asof: str = typer.Option(None, help="Simulate running on this date (uses data up to it)"),
    no_update: bool = typer.Option(False, help="Skip the data refresh"),
) -> None:
    """Refresh data, advance the paper ledger, and write today's report."""
    from . import paper, report

    cfg = load_config()
    instruments = inst.load_instruments(cfg.data_dir)
    if not no_update and asof is None:
        update(None, "yfinance")  # refresh the whole universe + benchmark
    st = paper.sync(cfg, instruments, asof)
    md, csv = report.write_report(cfg, st)
    if st.result is not None:
        r = st.result
        typer.echo(
            f"swing sleeve | {st.last_date.date()} | regime {st.regime} | equity {r.equity['equity'].iloc[-1]:,.0f} | "
            f"{len(r.positions)} open | {len(r.pending)} orders for next session"
        )
    else:
        typer.echo(f"{st.last_date.date()} | regime {st.regime}")
    if st.mom:
        m = st.mom.result
        typer.echo(
            f"momentum sleeve | value {m.equity['value'].iloc[-1]:,.0f} (paid in {m.equity['deposited'].iloc[-1]:,.0f}) | {len(m.positions)} holdings | "
            f"{len(m.pending_sells)} sells, {len(m.pending_buys)} buys queued"
        )
    for slug, cs in st.cands.items():
        m = cs.result
        typer.echo(
            f"candidate {slug} ({cs.tier}) | value {m.equity['value'].iloc[-1]:,.0f} (paid in {m.equity['deposited'].iloc[-1]:,.0f}) | {len(m.positions)} holdings | "
            f"{len(m.pending_sells)} sells, {len(m.pending_buys)} buys queued"
        )
    for slug, why in st.cand_errors.items():
        typer.echo(f"candidate {slug}: {why}")
    typer.echo(f"report: {md}\norders: {csv}")
    if st.stale:
        typer.echo("WARNING: data looks stale; run `trader update`.")
    from . import sessions

    if w := sessions.holiday_list_warning():
        typer.echo(w)


@app.command()
def momentum(
    from_: str = typer.Option("2018-01-01", "--from", help="Backtest start date"),
    to: str = typer.Option(None, help="End date (default: last bar)"),
    lookback: int = typer.Option(None), skip: int = typer.Option(None),
    top_n: int = typer.Option(None), buffer: int = typer.Option(None),
    bear_exit: bool = typer.Option(None, help="Sell everything when the market turns bearish"),
    out: str = typer.Option("reports/momentum", help="Output directory"),
    liquid_top: int = typer.Option(None, help="Only the N most liquid names each day (survivorship guard)"),
    pit: bool = typer.Option(False, help="Point-in-time universe: only stocks that were in the NIFTY 500 on each day (data/membership)"),
) -> None:
    """Backtest the momentum rotation strategy (config.yaml `momentum:` unless overridden)."""
    import json

    import pandas as pd

    from . import backtest as bt
    from . import momentum as mom
    from .config import ROOT

    cfg = load_config()
    c = cfg.momentum
    p = mom.MomParams(
        lookback or c.lookback, skip if skip is not None else c.skip, top_n or c.top_n,
        buffer if buffer is not None else c.buffer, c.bear_exit if bear_exit is None else bear_exit,
    )
    prep = mom.prepare(cfg, inst.load_instruments(cfg.data_dir), liquid_top, pit)
    res = mom.run(cfg, prep, p, pd.Timestamp(from_), pd.Timestamp(to) if to else None)
    outdir = ROOT / out
    outdir.mkdir(parents=True, exist_ok=True)
    res.trades.to_csv(outdir / "trades.csv", index=False)
    res.equity.to_csv(outdir / "equity.csv")
    typer.echo(p.label())
    typer.echo(json.dumps(mom.summarize(res.equity, res.trades, bt.load_benchmark(cfg)), indent=2))
    typer.echo(f"turnover per year: {res.turnover_per_year:.2f}x equity")
    typer.echo("\nCaveat: " + ("point-in-time NIFTY 500 membership from dated snapshots (gaps between snapshots; delisted stocks without prices are missing)."
                              if pit else "universe = today's NIFTY 500 constituents (survivorship bias, which flatters momentum most)."))


@app.command("momentum-wf")
def momentum_wf(
    out: str = typer.Option("reports/momentum-wf", help="Output directory"),
    liquid_top: int = typer.Option(None, help="Only the N most liquid names each day (survivorship guard)"),
    pit: bool = typer.Option(False, help="Point-in-time universe: only stocks that were in the NIFTY 500 on each day (data/membership)"),
) -> None:
    """Walk-forward the momentum strategy (3y in-sample / 1y OOS) and compare with buy-and-hold."""
    import json

    import pandas as pd

    from . import backtest as bt
    from . import momentum as mom
    from .config import ROOT

    cfg = load_config()
    prep = mom.prepare(cfg, inst.load_instruments(cfg.data_dir), liquid_top, pit)
    res = mom.walk_forward(cfg, prep)
    bench = bt.load_benchmark(cfg)
    outdir = ROOT / out
    outdir.mkdir(parents=True, exist_ok=True)
    folds = pd.DataFrame(res["folds"])
    folds.to_csv(outdir / "folds.csv", index=False)
    res["equity"].to_csv(outdir / "oos_equity.csv")
    res["trades"].to_csv(outdir / "oos_trades.csv", index=False)
    typer.echo(folds.to_string(index=False))
    typer.echo("\n== MOMENTUM WALK-FORWARD (out-of-sample, params chosen in-sample) ==")
    typer.echo(json.dumps(mom.summarize(res["equity"], res["trades"], bench), indent=2))
    typer.echo("\nRobustness: every grid point on the same OOS windows (informational, not used for selection)")
    for label, eq in res["grid"].items():
        m = mom.summarize(eq, pd.DataFrame(), bench)
        typer.echo(f"  {label:34s} CAGR {m['cagr_pct']:>6}%  maxDD {m['max_drawdown_pct']:>7}%  Sharpe {m['sharpe']}")
    typer.echo("\nCaveat: " + ("point-in-time NIFTY 500 membership from dated snapshots (gaps between snapshots; delisted stocks without prices are missing)."
                              if pit else "universe = today's NIFTY 500 constituents (survivorship bias, which flatters momentum most)."))


@app.command("membership-snapshot")
def membership_snapshot() -> None:
    """Save today's official NIFTY 500 list as a dated snapshot (point-in-time universe data; run about monthly)."""
    from .data import membership

    typer.echo(f"saved {membership.save_current_snapshot(load_config().data_dir)}")


@app.command("membership-fetch")
def membership_fetch() -> None:
    """Download prices for past NIFTY 500 members missing from the candle store; unavailable ones go to data/membership/unavailable.csv."""
    from .data import membership

    out = membership.fetch_missing(load_config())
    typer.echo(f"fetched {int((out['rows'] > 0).sum()) if len(out) else 0}, unavailable {int((out['rows'] == 0).sum()) if len(out) else 0}")


@app.command("fundamentals-snapshot")
def fundamentals_snapshot(
    if_stale_days: int = typer.Option(0, help="Skip when the newest snapshot is younger than this many days"),
    limit: int = typer.Option(0, help="Only the first N instruments (testing)"),
) -> None:
    """Save today's fundamentals for every instrument (dated, so strategies only see what was known)."""
    import pandas as pd

    from .data import fundamentals as fund

    cfg = load_config()
    fdir = cfg.data_dir / "fundamentals"
    last = fund.latest_snapshot_date(fdir)
    today = pd.Timestamp(fund.ist_today())
    if if_stale_days and last is not None and (today - last).days < if_stale_days:
        typer.echo(f"newest snapshot {last.date()} is {(today - last).days}d old (< {if_stale_days}); skipping")
        return
    syms = list(inst.load_instruments(cfg.data_dir)["symbol"])
    syms = syms[:limit] if limit else syms
    path, n, failed = fund.snapshot(fdir, syms)
    typer.echo(f"{n}/{len(syms)} saved to {path}")
    if failed:
        typer.echo(f"{len(failed)} failed: {', '.join(failed[:40])}{' ...' if len(failed) > 40 else ''}")


@app.command("research-eval")
def research_eval(
    slug: str = typer.Argument(..., help="Candidate in src/trader/research/candidates/<slug>.py"),
    recheck: bool = typer.Option(False, help="Informational re-run of an earlier candidate: not counted as a new trial"),
) -> None:
    """Run the fixed research gates on a candidate and record the trial (append-only)."""
    from .research import evaluate

    cfg = load_config()
    res = evaluate.evaluate(cfg, inst.load_instruments(cfg.data_dir), slug, record=True, counted=not recheck)
    typer.echo(res.summary_md)
    typer.echo(f"VERDICT: {res.verdict}  (reports/research/{slug}/summary.md)")
    if res.verdict in ("PASS", "FORWARD_ONLY"):
        typer.echo(f"Next: `trader research-promote {slug}` starts a forward paper sleeve (paper only).")


@app.command("research-promote")
def research_promote(slug: str = typer.Argument(...)) -> None:
    """Freeze a candidate that passed research-eval into the paper ledger as its own forward-only sleeve."""
    from . import paper

    cfg = load_config()
    e = paper.promote_candidate(cfg, inst.load_instruments(cfg.data_dir), slug)
    typer.echo(f"{slug} promoted ({e['tier']}): forward paper sleeve from {e['start']}, capital {e['capital']:,.0f}, "
               f"frozen params {e['params']}. Paper only; its backtest is not evidence.")


@app.command("research-retire")
def research_retire(slug: str = typer.Argument(...)) -> None:
    """Stop replaying a candidate sleeve (its trials stay in the registry)."""
    from . import paper

    paper.retire_candidate(load_config(), slug)
    typer.echo(f"{slug} retired.")


@app.command("research-status")
def research_status() -> None:
    """Trial count, recent trials, active candidate sleeves, data freshness and the backlog head."""
    import pandas as pd

    from . import paper
    from .config import ROOT
    from .data import fundamentals as fund
    from .data.sources import BENCHMARK
    from .research import registry

    cfg = load_config()
    last_bar = store.load(cfg.candles_dir, BENCHMARK).index.max()
    snap = fund.latest_snapshot_date(cfg.data_dir / "fundamentals")
    typer.echo(f"last candle bar: {last_bar.date()} | last completed session: {store.last_complete_day()} "
               f"| newest fundamentals snapshot: {snap.date() if snap is not None else 'none'}")
    typer.echo(f"counted trials so far: {registry.trial_count(cfg)}")
    for t in registry.recent_trials(cfg):
        typer.echo(f"  #{t['id']} {t['ts']} {t['slug']}: {t['verdict']}{'' if t['counted'] else ' (recheck)'}")
    cands = paper.candidate_entries(cfg)
    typer.echo(f"candidate sleeves ({sum(1 for e in cands.values() if e.get('active'))}/{paper.MAX_ACTIVE_CANDIDATES} active):")
    for slug, e in cands.items():
        typer.echo(f"  {slug}: {'active' if e.get('active') else 'retired'} {e['tier']} since {e['start']}")
    bl = ROOT / "research" / "backlog.md"
    typer.echo("\nbacklog (research/backlog.md):")
    typer.echo("\n".join(bl.read_text().splitlines()[:40]) if bl.exists() else "  (missing)")


@app.command("market-context")
def market_context_cmd() -> None:
    """Print a market snapshot (regime, trend, returns, volatility, breadth). Informational: for research journals only."""
    from . import momentum as mom
    from .data.sources import BENCHMARK
    from .research import context

    cfg = load_config()
    bench = store.load(cfg.candles_dir, BENCHMARK)["close"]
    prep = mom.prepare(cfg, inst.load_instruments(cfg.data_dir), None)
    typer.echo(context.render(context.market_context(bench, prep)))
    typer.echo("\nInformational only: it never changes the gates, the grid, or which idea is tested.")


if __name__ == "__main__":
    app()
