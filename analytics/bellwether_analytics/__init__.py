"""Bellwether analytics — computation over canonical data produced by ingestion."""

from .kalshi_flow import FlowAggregator, MarketFlow
from .paper_trade import PaperResult, PaperTradeSimulator
from .specialization import category_breakdown
from .wallet_scoring import WalletScore, rank_wallets, score_wallet

__version__ = "0.2.0"

__all__ = [
    "FlowAggregator",
    "MarketFlow",
    "PaperResult",
    "PaperTradeSimulator",
    "category_breakdown",
    "WalletScore",
    "rank_wallets",
    "score_wallet",
]
