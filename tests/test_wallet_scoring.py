from tradertracker.polymarket.data_api import Position, Trade
from tradertracker.polymarket.wallet_scoring import rank_wallets, score_wallet


def _trade(slug: str, size: float, price: float, side: str = "BUY", ts: int = 0) -> Trade:
    return Trade(
        proxyWallet="0xA",
        side=side,
        asset="0",
        conditionId="c1",
        size=size,
        price=price,
        timestamp=ts,
        slug=slug,
        outcome="YES",
        outcomeIndex=0,
    )


def _position(size: float, realized: float, redeemable: bool = False) -> Position:
    return Position(
        size=size,
        realizedPnl=realized,
        cashPnl=0.0,
        redeemable=redeemable,
    )


def test_score_wallet_basic_aggregation():
    trades = [
        _trade("fed-rates-january", 100, 0.40),
        _trade("fed-rates-march", 200, 0.50),
        _trade("nfl-week-12", 50, 0.30),
    ]
    positions = [
        _position(0, 100),   # resolved winner
        _position(0, -25),   # resolved loser
        _position(50, 0),    # open
    ]
    s = score_wallet("0xA", trades, positions)
    assert s.trade_count == 3
    # 100*.4 + 200*.5 + 50*.3 = 40 + 100 + 15 = 155
    assert round(s.total_volume, 2) == 155.0
    assert s.realized_pnl == 75.0
    assert s.resolved_positions == 2
    assert s.win_rate == 0.5
    assert s.top_category == "fed"
    # "fed-*" volume = 140 / 155 ≈ 0.903
    assert 0.90 <= s.category_concentration <= 0.91
    assert s.open_positions == 1


def test_rank_wallets_filters_by_thresholds():
    skilled_trades = [_trade("crypto-btc-1", 10, 0.5) for _ in range(60)]
    skilled_positions = [_position(0, 100) for _ in range(8)] + [_position(0, -10) for _ in range(2)]
    skilled = score_wallet("0xSKILL", skilled_trades, skilled_positions)

    weak_trades = [_trade("politics-pres-1", 10, 0.5) for _ in range(60)]
    weak_positions = [_position(0, -100) for _ in range(8)] + [_position(0, 20) for _ in range(2)]
    weak = score_wallet("0xWEAK", weak_trades, weak_positions)

    too_few = score_wallet("0xSMALL", [_trade("sports-1", 1, 0.5)], [_position(0, 1)])

    ranked = rank_wallets([skilled, weak, too_few], min_trades=50, min_win_rate=0.55, min_pnl=0.0)
    assert [r.wallet for r in ranked] == ["0xSKILL"]


def test_weighted_score_responds_to_components():
    base_trades = [_trade("a", 10, 0.5) for _ in range(10)]
    s_low = score_wallet("0xA", base_trades, [_position(0, -1000)])
    s_high = score_wallet("0xA", base_trades, [_position(0, 50_000)])
    assert s_high.weighted_score() > s_low.weighted_score()
