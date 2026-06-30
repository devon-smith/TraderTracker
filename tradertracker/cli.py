"""TraderTracker CLI.

  tt poly leaderboard            list top Polymarket wallets
  tt poly wallet <addr>          summarize a wallet (trades + positions + score)
  tt poly rank <addr>...         rank multiple wallets with smart-money filter
  tt poly categories <addr>      category breakdown for a wallet
  tt poly paper <addr>           paper-trade replay of a leader's history
  tt kalshi flow [--ticker T]    aggregate anonymous flow across markets
"""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .analytics import PaperTradeSimulator, category_breakdown
from .kalshi import FlowAggregator, KalshiClient
from .polymarket import DataAPIClient, GammaClient, rank_wallets, score_wallet

app = typer.Typer(help="TraderTracker — prediction-market wallet tracking.", no_args_is_help=True)
poly = typer.Typer(help="Polymarket commands.")
kalshi_app = typer.Typer(help="Kalshi commands.")
app.add_typer(poly, name="poly")
app.add_typer(kalshi_app, name="kalshi")

console = Console()


@poly.command("leaderboard")
def poly_leaderboard(
    window: str = typer.Option("month", help="day | week | month | all"),
    limit: int = typer.Option(25),
):
    """Show the official Polymarket leaderboard."""
    with GammaClient() as g:
        entries = g.leaderboard(window=window, limit=limit)
    table = Table(title=f"Polymarket leaderboard — {window}")
    table.add_column("Rank", justify="right")
    table.add_column("Wallet")
    table.add_column("Username")
    table.add_column("Volume", justify="right")
    table.add_column("PnL", justify="right")
    for e in entries:
        table.add_row(
            str(e.rank or ""),
            (e.proxyWallet or "")[:10] + "…",
            e.userName or "",
            f"{e.vol:,.0f}" if e.vol else "",
            f"{e.pnl:,.0f}" if e.pnl is not None else "",
        )
    console.print(table)


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
    table.add_column("Wallet")
    table.add_column("Trades", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("PnL", justify="right")
    table.add_column("Win%", justify="right")
    table.add_column("Top cat")
    table.add_column("Concen.", justify="right")
    table.add_column("Score", justify="right")
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
    table.add_column("Category")
    table.add_column("Trades", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("Share", justify="right")
    table.add_column("Net buy", justify="right")
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
        agg.update(
            k.iter_trades(ticker=ticker, min_ts=min_ts, max_ts=max_ts, max_pages=pages)
        )
    rows = agg.top_imbalances(n=top, min_notional=min_notional)
    table = Table(title="Kalshi flow imbalances")
    table.add_column("Ticker")
    table.add_column("Trades", justify="right")
    table.add_column("Total $", justify="right")
    table.add_column("YES $", justify="right")
    table.add_column("NO $", justify="right")
    table.add_column("Imbalance", justify="right")
    table.add_column("Block $", justify="right")
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


if __name__ == "__main__":
    app()
