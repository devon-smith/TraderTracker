from bellwether_ingestion.polymarket.categorize import gamma_market_fields, normalize_category


def test_category_from_slug_keywords():
    assert normalize_category({"slug": "btc-updown-5m-1782846000"}) == "crypto"
    assert normalize_category({"slug": "fifwc-fra-swe-2026-06-30-fra"}) == "sports"
    assert normalize_category({"slug": "will-joe-biden-get-coronavirus"}) == "politics"
    assert normalize_category({"slug": "will-the-fed-cut-rates-in-march"}) == "economics"
    assert normalize_category({"slug": "some-random-question"}) == "other"


def test_category_prefers_explicit_field_then_tags():
    assert normalize_category({"category": "Crypto", "slug": "x"}) == "crypto"
    assert normalize_category({"tags": [{"label": "Politics"}], "slug": "x"}) == "politics"


def test_gamma_market_fields_resolution_from_prices():
    closed = gamma_market_fields(
        {
            "conditionId": "0xabc",
            "question": "Will X happen?",
            "slug": "will-x-happen",
            "closed": True,
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["1", "0"]',
            "closedTime": "2026-01-01T00:00:00Z",
            "createdAt": "2025-01-01T00:00:00Z",
        }
    )
    assert closed["external_id"] == "0xabc"
    assert closed["resolution"] == "Yes"
    assert closed["is_multi_outcome"] is False
    assert closed["resolved_at"] is not None
    assert closed["created_at"] is not None

    open_market = gamma_market_fields(
        {"conditionId": "0xdef", "slug": "btc-updown", "closed": False,
         "outcomes": '["Up", "Down"]', "outcomePrices": '["0.5", "0.5"]'}
    )
    assert open_market["resolution"] is None
    assert open_market["resolved_at"] is None
    assert open_market["category"] == "crypto"
