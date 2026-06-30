"""Strategy detection.

Accounts are the unit Polymarket exposes, but the durable signal is the *strategy*:
a behavioral template run repeatedly — across many markets in a recurring family
(scalping `btc-updown-5m-*`), across many accounts (the same archetype showing up
again and again), or as copy/follow chains (B fills right after A).

Pipeline:
  features.extract_features   per-wallet behavioral vector (cadence, two-sidedness,
                              round-tripping, recurrence, split/merge/redeem mix)
  archetypes.classify         explainable rule-based archetype label per wallet
  recurrence.strategy_templates   (archetype, market-family) repeated across accounts
  leadlag.detect_followers    wallets that systematically trade just after another
"""

from .archetypes import STRATEGY_ARCHETYPES, StrategyConfig, classify
from .features import extract_features
from .leadlag import detect_followers
from .recurrence import market_family, strategy_templates, wallet_family_recurrence

__all__ = [
    "extract_features",
    "classify",
    "StrategyConfig",
    "STRATEGY_ARCHETYPES",
    "market_family",
    "wallet_family_recurrence",
    "strategy_templates",
    "detect_followers",
]
