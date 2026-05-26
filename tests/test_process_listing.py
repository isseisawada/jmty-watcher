"""inquiry_closed の listing がパイプラインで分類・通知されないこと。"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

from watcher.main import process_listing
from watcher.models import Classification, Listing


def _make_listing(inquiry_closed: bool) -> Listing:
    return Listing(
        article_id="article-test",
        url="https://jmty.jp/x/sale/article-test",
        title="t",
        price_yen=1000,
        prefecture=None,
        city=None,
        category_label=None,
        thumbnail_url=None,
        inquiry_closed=inquiry_closed,
    )


def _classification() -> Classification:
    return Classification(
        is_actual_trailer_house=True,
        seller_type="individual",
        trailer_category="residential",
        estimated_market_price_yen=1500,
        price_gap_ratio=0.5,
        condition_grade="A",
        priority="S",
        concerns=[],
        sales_pitch_hook="",
        model_version="x",
    )


def _mocks(*, classification: Classification | None = None) -> dict[str, Any]:
    db = MagicMock()
    db.upsert_listing.return_value = "uuid-1"
    classifier = MagicMock()
    classifier.classify.return_value = classification or _classification()
    return {
        "db": db,
        "classifier": classifier,
        "dm_generator": MagicMock(),
        "notifier": MagicMock(),
        "sheets": MagicMock(),
    }


def test_inquiry_closed_listing_returns_none_and_skips_pipeline() -> None:
    listing = _make_listing(inquiry_closed=True)
    m = _mocks()
    result = process_listing(
        listing=listing,
        today=date(2026, 5, 21),
        dry_run=False,
        **m,
    )
    # 受付終了は None を返してパイプラインをスキップ
    assert result is None
    m["db"].upsert_listing.assert_called_once()
    m["classifier"].classify.assert_not_called()
    m["dm_generator"].generate.assert_not_called()
    m["notifier"].post_listing.assert_not_called()
    m["sheets"].append_listing.assert_not_called()
    m["db"].insert_classification.assert_not_called()


def test_open_listing_priority_s_runs_full_pipeline_and_returns_classification() -> None:
    listing = _make_listing(inquiry_closed=False)
    m = _mocks()
    result = process_listing(
        listing=listing,
        today=date(2026, 5, 21),
        dry_run=False,
        **m,
    )
    # Classification がそのまま返る（priority=S）
    assert result is not None
    assert result.priority == "S"

    m["db"].upsert_listing.assert_called_once()
    m["classifier"].classify.assert_called_once()
    m["dm_generator"].generate.assert_called_once()
    m["notifier"].post_listing.assert_called_once()
    m["sheets"].append_listing.assert_called_once()


def test_open_listing_priority_c_returns_classification_but_no_notify() -> None:
    """priority=C (非トレーラーハウス) は通知対象外 → Slack/Sheets 呼ばれない。

    bulk_backfill 側で priority を見て『Sheets 追加件数』としてカウントしない
    判断をするため、Classification は必ず返す。
    """
    listing = _make_listing(inquiry_closed=False)
    c_listing = Classification(
        is_actual_trailer_house=False,
        seller_type="individual",
        trailer_category="unknown",
        estimated_market_price_yen=None,
        price_gap_ratio=None,
        condition_grade="C",
        priority="C",
        concerns=[],
        sales_pitch_hook="",
        model_version="x",
    )
    m = _mocks(classification=c_listing)
    result = process_listing(
        listing=listing,
        today=date(2026, 5, 21),
        dry_run=False,
        **m,
    )
    assert result is not None
    assert result.priority == "C"

    m["classifier"].classify.assert_called_once()
    m["db"].insert_classification.assert_called_once()
    # NOTIFY_PRIORITIES = {S,A,B} に含まれないので通知系は呼ばれない
    m["notifier"].post_listing.assert_not_called()
    m["sheets"].append_listing.assert_not_called()
