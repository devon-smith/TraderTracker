"""Bellwether CLI (`tt`).

  tt poly leaderboard            list top Polymarket wallets
  tt poly wallet <addr>          summarize a wallet (trades + positions + score)
  tt poly rank <addr>...         rank multiple wallets with smart-money filter
  tt poly categories <addr>      category breakdown for a wallet
  tt poly paper <addr>           paper-trade replay of a leader's history
  tt kalshi flow [--ticker T]    aggregate anonymous flow across markets
  tt db init                     apply canonical schema migrations
"""

from __future__ import annotations

from typing import Optional

import typer
from bellwether_ingestion.kalshi import KalshiClient
from bellwether_ingestion.polymarket import DataAPIClient, GammaClient
from rich.console import Console
from rich.table import Table

from . import (
    FlowAggregator,
    PaperTradeSimulator,
    category_breakdown,
    rank_wallets,
    score_wallet,
)

app = typer.Typer(help="Bellwether — prediction-market trader intelligence.", no_args_is_help=True)
poly = typer.Typer(help="Polymarket commands.")
kalshi_app = typer.Typer(help="Kalshi commands.")
manifold_app = typer.Typer(help="Manifold commands.")
analyze_app = typer.Typer(help="Analytics over the canonical tables.")
candidates_app = typer.Typer(help="Candidate pool + validation (Phase 3).")
strategy_app = typer.Typer(help="Strategy detection (archetypes, templates, copy chains).")
db_app = typer.Typer(help="Database commands.")
app.add_typer(poly, name="poly")
app.add_typer(kalshi_app, name="kalshi")
app.add_typer(manifold_app, name="manifold")
app.add_typer(analyze_app, name="analyze")
app.add_typer(candidates_app, name="candidates")
app.add_typer(strategy_app, name="strategy")
app.add_typer(db_app, name="db")

console = Console()


def _columns(table: Table, *specs: tuple[str, str]) -> None:
    for name, just in specs:
        table.add_column(name, justify=just)


@poly.command("leaderboard")
def poly_leaderboard(
    window: str = typer.Option("month", help="day | week | month | all"),
    limit: int = typer.Option(25),
):
    """Show the official Polymarket leaderboard."""
    with GammaClient() as g:
        entries = g.leaderboard(window=window, limit=limit)
    table = Table(title=f"Polymarket leaderboard — {window}")
    _columns(
        table,
        ("Rank", "right"), ("Wallet", "left"), ("Username", "left"),
        ("Volume", "right"), ("PnL", "right"),
    )
    for e in entries:
        table.add_row(
            str(e.rank or ""),
            (e.proxyWallet or "")[:10] + "…",
            e.userName or "",
            f"{e.vol:,.0f}" if e.vol else "",
            f"{e.pnl:,.0f}" if e.pnl is not None else "",
        )
    console.print(table)


@poly.command("load")
def poly_load(
    address: str = typer.Argument(..., help="EOA or proxy wallet address"),
    max_trade_pages: int = typer.Option(200),
    max_markets: Optional[int] = typer.Option(None, help="Cap distinct markets fetched"),
):
    """Backfill a Polymarket wallet's trade + activity history into the canonical tables."""
    from bellwether_ingestion.polymarket import run_load_wallet

    nt, ne = run_load_wallet(address, max_trade_pages=max_trade_pages, max_markets=max_markets)
    console.print(f"[green]wrote {nt} trades, {ne} position events[/green] for {address}")


@poly.command("seed-leaderboard")
def poly_seed_leaderboard(
    n: int = typer.Argument(100),
    window: str = typer.Option("month", help="day | week | month | all"),
):
    """Seed the wallet pool from the Gamma leaderboard."""
    from bellwether_ingestion.polymarket import run_seed_leaderboard

    c = run_seed_leaderboard(n, window=window)
    console.print(f"[green]seeded {c} wallets[/green] from the {window} leaderboard")


@poly.command("wallet")
def poly_wallet(
    address: str = typer.Argument(..., help="EOA or proxy wallet address"),
    pages: int = typer.Option(20, help="Max trade pages to pull (500/page)"),
):
    """Summarize a single Polymarket wallet."""
    with DataAPIClient() as d:
        trades = list(d.iter_trades(user=address, max_pages=pages))
        positions = d.positions(user=address)
    s = score_wallet(address, trades, positions)
    console.print_json(data={
        "wallet": s.wallet,
        "trades": s.trade_count,
        "volume": round(s.total_volume, 2),
        "realized_pnl": round(s.realized_pnl, 2),
        "unrealized_pnl": round(s.unrealized_pnl, 2),
        "total_pnl": round(s.total_pnl, 2),
        "win_rate": s.win_rate,
        "resolved_positions": s.resolved_positions,
        "open_positions": s.open_positions,
        "top_category": s.top_category,
        "category_concentration": round(s.category_concentration, 3),
        "score": round(s.weighted_score(), 4),
    })


@poly.command("rank")
def poly_rank(
    addresses: list[str] = typer.Argument(..., help="One or more wallet addresses"),
    min_trades: int = typer.Option(50),
    min_win_rate: float = typer.Option(0.55),
    min_pnl: float = typer.Option(0.0),
    require_resolved: int = typer.Option(10),
    pages: int = typer.Option(10),
):
    """Score multiple wallets and rank survivors of the smart-money filter."""
    scored = []
    with DataAPIClient() as d:
        for addr in addresses:
            trades = list(d.iter_trades(user=addr, max_pages=pages))
            positions = d.positions(user=addr)
            scored.append(score_wallet(addr, trades, positions))

    ranked = rank_wallets(
        scored,
        min_trades=min_trades,
        min_win_rate=min_win_rate,
        min_pnl=min_pnl,
        require_resolved=require_resolved,
    )

    table = Table(title="Ranked wallets")
    _columns(
        table,
        ("Wallet", "left"), ("Trades", "right"), ("Volume", "right"), ("PnL", "right"),
        ("Win%", "right"), ("Top cat", "left"), ("Concen.", "right"), ("Score", "right"),
    )
    for s in ranked:
        table.add_row(
            s.wallet[:10] + "…",
            str(s.trade_count),
            f"{s.total_volume:,.0f}",
            f"{s.total_pnl:,.0f}",
            f"{s.win_rate:.1%}" if s.win_rate is not None else "—",
            s.top_category or "",
            f"{s.category_concentration:.0%}",
            f"{s.weighted_score():.3f}",
        )
    console.print(table)
    skipped = len(scored) - len(ranked)
    if skipped:
        console.print(f"[dim]{skipped} wallet(s) filtered out by thresholds.[/dim]")


@poly.command("categories")
def poly_categories(
    address: str = typer.Argument(...),
    pages: int = typer.Option(20),
):
    """Category breakdown for a wallet's trade history."""
    with DataAPIClient() as d:
        trades = list(d.iter_trades(user=address, max_pages=pages))
    rows = category_breakdown(trades)
    table = Table(title=f"Category breakdown for {address[:10]}…")
    _columns(
        table,
        ("Category", "left"), ("Trades", "right"), ("Volume", "right"),
        ("Share", "right"), ("Net buy", "right"),
    )
    for r in rows[:25]:
        table.add_row(
            r["category"],
            str(r["trades"]),
            f"{r['volume']:,.0f}",
            f"{r['share']:.1%}",
            f"{r['net_buy']:,.0f}",
        )
    console.print(table)


@poly.command("paper")
def poly_paper(
    address: str = typer.Argument(...),
    pages: int = typer.Option(20),
    size_scale: float = typer.Option(0.05, help="Fraction of leader notional you'd copy"),
    slippage_bps: float = typer.Option(200.0, help="Slippage applied to each copy fill"),
    min_notional: float = typer.Option(100.0, help="Skip leader trades below this notional"),
    same_side_only: bool = typer.Option(False, help="Only copy BUY fills"),
):
    """Paper-trade replay against a leader's history."""
    with DataAPIClient() as d:
        trades = list(d.iter_trades(user=address, max_pages=pages))
    sim = PaperTradeSimulator(
        slippage_bps=slippage_bps,
        size_scale=size_scale,
        min_leader_notional=min_notional,
        same_side_only=same_side_only,
    )
    result = sim.run(leader=address, trades=trades)
    console.print_json(data=result.summary())


@kalshi_app.command("flow")
def kalshi_flow(
    ticker: Optional[str] = typer.Option(None, help="Filter to a specific Kalshi ticker"),
    min_ts: Optional[int] = typer.Option(None, help="Unix seconds; lower bound"),
    max_ts: Optional[int] = typer.Option(None, help="Unix seconds; upper bound"),
    pages: int = typer.Option(5),
    top: int = typer.Option(20, help="Show top-N imbalances"),
    min_notional: float = typer.Option(1000.0),
):
    """Aggregate anonymous Kalshi trades into per-market flow imbalances."""
    agg = FlowAggregator()
    with KalshiClient() as k:
        agg.update(k.iter_trades(ticker=ticker, min_ts=min_ts, max_ts=max_ts, max_pages=pages))
    rows = agg.top_imbalances(n=top, min_notional=min_notional)
    table = Table(title="Kalshi flow imbalances")
    _columns(
        table,
        ("Ticker", "left"), ("Trades", "right"), ("Total $", "right"), ("YES $", "right"),
        ("NO $", "right"), ("Imbalance", "right"), ("Block $", "right"),
    )
    for f in rows:
        table.add_row(
            f.ticker,
            str(f.trades_seen),
            f"{f.total_notional:,.0f}",
            f"{f.yes_notional:,.0f}",
            f"{f.no_notional:,.0f}",
            f"{f.imbalance:+.2f}",
            f"{f.block_trade_notional:,.0f}",
        )
    console.print(table)


@manifold_app.command("load")
def manifold_load(
    identifier: str = typer.Argument(..., help="Manifold username or user id"),
    max_pages: int = typer.Option(200),
    max_bets: Optional[int] = typer.Option(None, help="Cap most-recent bets processed"),
):
    """Backfill a Manifold user's bet history into the canonical tables."""
    from bellwether_ingestion.manifold import run_load_user

    n = run_load_user(identifier, max_pages=max_pages, max_bets=max_bets)
    console.print(f"[green]wrote {n} new trades[/green] for {identifier}")


@analyze_app.command("rank")
def analyze_rank(
    platform: Optional[str] = typer.Option(None, help="manifold | polymarket | kalshi"),
    config: Optional[str] = typer.Option(None, help="Path to a ranking YAML/TOML config"),
    min_resolved_trades: int = typer.Option(1, help="Used when --config is not given"),
    min_win_rate: float = typer.Option(0.0, help="Used when --config is not given"),
    top: int = typer.Option(25),
):
    """Rank wallets from the canonical tables (performance + specialization)."""
    from bellwether_analytics.core import (
        RankConfig,
        load_config,
        load_trades_df,
        performance_by_wallet,
        rank,
        specialization_by_wallet,
    )

    df = load_trades_df(platform=platform)
    if df.empty:
        console.print("[yellow]No trades found. Load some first (e.g. tt manifold load).[/yellow]")
        return
    perf = performance_by_wallet(df)
    spec = specialization_by_wallet(df)
    cfg = (
        load_config(config)
        if config
        else RankConfig(min_resolved_trades=min_resolved_trades, min_win_rate=min_win_rate)
    )
    ranked = rank(perf, spec, cfg).head(top)

    table = Table(title=f"Ranked wallets ({platform or 'all'})")
    _columns(
        table,
        ("Wallet", "left"), ("Resolved", "right"), ("Win%", "right"),
        ("PnL", "right"), ("ROI", "right"), ("HHI", "right"),
        ("Top cat", "left"), ("Score", "right"),
    )
    for wallet, r in ranked.iterrows():
        wr = r.get("win_rate")
        roi = r.get("roi")
        table.add_row(
            str(wallet)[:12] + "…",
            str(int(r.get("resolved_trade_count") or 0)),
            f"{wr:.0%}" if wr == wr and wr is not None else "—",  # NaN-safe
            f"{r.get('realized_pnl', float('nan')):,.0f}",
            f"{roi:.0%}" if roi == roi and roi is not None else "—",
            f"{r.get('hhi', float('nan')):.2f}",
            str(r.get("top_category") or ""),
            f"{r.get('score', float('nan')):.3f}",
        )
    console.print(table)
    console.print(f"[dim]{len(ranked)} wallet(s) after filters.[/dim]")


@candidates_app.command("build")
def candidates_build(
    platform: str = typer.Option("polymarket", help="manifold | polymarket"),
    min_resolved_trades: int = typer.Option(50),
    min_win_rate: float = typer.Option(0.55),
    target_size: int = typer.Option(500),
    persist: bool = typer.Option(True, help="Upsert into candidate_score"),
    top: int = typer.Option(25),
):
    """Build (and persist) the ranked candidate pool from the canonical tables."""
    from bellwether_analytics.candidates import PoolConfig, build_pool, persist_pool
    from bellwether_analytics.core import load_events_df, load_trades_df

    tr = load_trades_df(platform=platform)
    ev = load_events_df(platform=platform)
    if tr.empty:
        console.print("[yellow]No trades loaded for this platform.[/yellow]")
        return
    cfg = PoolConfig(min_resolved_trades=min_resolved_trades, min_win_rate=min_win_rate, target_size=target_size)
    pool = build_pool(tr, ev, cfg)
    if pool.empty:
        console.print("[yellow]No wallets passed the filters. Loosen thresholds or load more data.[/yellow]")
        return
    if persist:
        n = persist_pool(pool, platform)
        console.print(f"[green]persisted {n} candidate scores[/green]")

    table = Table(title=f"Candidate pool ({platform}) — top {top}")
    _columns(table, ("Wallet", "left"), ("Resolved", "right"), ("Win%", "right"),
             ("PnL", "right"), ("HHI", "right"), ("Score", "right"))
    for wallet, r in pool.head(top).iterrows():
        wr = r.get("win_rate")
        table.add_row(
            str(wallet)[:12] + "…",
            str(int(r.get("resolved_trade_count") or 0)),
            f"{wr:.0%}" if wr == wr and wr is not None else "—",
            f"{r.get('realized_pnl', float('nan')):,.0f}",
            f"{r.get('hhi', float('nan')):.2f}",
            f"{r.get('score', float('nan')):.3f}",
        )
    console.print(table)


@candidates_app.command("validate")
def candidates_validate(
    split_ts: str = typer.Argument(..., help="ISO timestamp, e.g. 2026-03-01"),
    platform: str = typer.Option("polymarket"),
):
    """Walk-forward out-of-sample validation + shuffled-label control."""
    from bellwether_analytics.candidates import walk_forward
    from bellwether_analytics.core import load_trades_df

    tr = load_trades_df(platform=platform)
    console.print_json(data=walk_forward(tr, split_ts=split_ts))


def _load_for_strategy(platform: str):
    from bellwether_analytics.core import load_events_df, load_trades_df

    return load_trades_df(platform=platform), load_events_df(platform=platform)


@strategy_app.command("classify")
def strategy_classify(
    platform: str = typer.Option("polymarket"),
    top: int = typer.Option(25),
):
    """Label each wallet with a strategy archetype + the reason."""
    from bellwether_analytics.strategy import classify, extract_features

    trades, events = _load_for_strategy(platform)
    if trades.empty:
        console.print("[yellow]No trades loaded.[/yellow]")
        return
    labeled = classify(extract_features(trades, events))
    table = Table(title=f"Strategy archetypes ({platform})")
    _columns(table, ("Wallet", "left"), ("Archetype", "left"), ("Tr/day", "right"),
             ("Net dir", "right"), ("Round-trip", "right"), ("Top family", "left"), ("Reason", "left"))
    for wallet, r in labeled.head(top).iterrows():
        table.add_row(
            str(wallet)[:12] + "…", str(r["archetype"]),
            f"{r['trades_per_day']:.0f}", f"{r['net_direction']:.2f}",
            f"{r['roundtrip_ratio']:.2f}", str(r.get("top_family") or "")[:20], str(r["reason"])[:40],
        )
    console.print(table)


@strategy_app.command("templates")
def strategy_templates_cmd(
    platform: str = typer.Option("polymarket"),
    min_wallets: int = typer.Option(2, help="Min distinct wallets running the template"),
):
    """Strategies implemented over and over: (archetype, market-family) across accounts."""
    from bellwether_analytics.strategy import classify, extract_features, strategy_templates

    trades, events = _load_for_strategy(platform)
    if trades.empty:
        console.print("[yellow]No trades loaded.[/yellow]")
        return
    arche = classify(extract_features(trades, events))["archetype"]
    tmpl = strategy_templates(trades, arche, min_wallets=min_wallets)
    if tmpl.empty:
        console.print(f"[yellow]No template run by >= {min_wallets} wallets yet (load more wallets).[/yellow]")
        return
    table = Table(title=f"Repeated strategy templates ({platform})")
    _columns(table, ("Archetype", "left"), ("Market family", "left"), ("Wallets", "right"), ("Volume", "right"))
    for _, r in tmpl.head(25).iterrows():
        table.add_row(str(r["archetype"]), str(r["family"])[:30], str(int(r["n_wallets"])), f"{r['volume']:,.0f}")
    console.print(table)


@strategy_app.command("recurrence")
def strategy_recurrence(
    wallet: str = typer.Argument(..., help="Wallet external id"),
    platform: str = typer.Option("polymarket"),
):
    """Temporal recurrence: does this wallet run the same cycle on a regular cadence?"""
    from bellwether_analytics.strategy import recurrence_in_time_report

    trades, events = _load_for_strategy(platform)
    if trades.empty:
        console.print("[yellow]No trades loaded.[/yellow]")
        return
    console.print_json(data=recurrence_in_time_report(trades, events, wallet))


@strategy_app.command("leadlag")
def strategy_leadlag(
    platform: str = typer.Option("polymarket"),
    max_lag: float = typer.Option(120.0, help="Max seconds between leader and follower fill"),
    min_events: int = typer.Option(3),
):
    """Detect copy/follow chains: wallets that trade just after another."""
    from bellwether_analytics.strategy import detect_followers

    trades, _ = _load_for_strategy(platform)
    pairs = detect_followers(trades, max_lag_seconds=max_lag, min_events=min_events)
    if pairs.empty:
        console.print("[yellow]No follow chains detected at these thresholds.[/yellow]")
        return
    table = Table(title=f"Lead-lag copy chains ({platform})")
    _columns(table, ("Leader", "left"), ("Follower", "left"), ("Follows", "right"),
             ("Markets", "right"), ("Follow %", "right"))
    for _, r in pairs.head(25).iterrows():
        table.add_row(str(r["leader"])[:12] + "…", str(r["follower"])[:12] + "…",
                      str(int(r["follow_events"])), str(int(r["n_markets"])), f"{r['follow_ratio']:.0%}")
    console.print(table)


@db_app.command("init")
def db_init():
    """Apply the canonical schema migrations (Alembic) to DATABASE_URL."""
    from bellwether_ingestion.db import upgrade_head

    upgrade_head()
    console.print("[green]Migrations applied (alembic upgrade head).[/green]")


if __name__ == "__main__":
    app()
