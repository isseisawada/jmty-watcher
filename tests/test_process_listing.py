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


def test_inquiry_closed_listing_is_upserted_but_not_classified() -> None:
    listing = _make_listing(inquiry_closed=True)
    m = _mocks()
    process_listing(
        listing=listing,
        today=date(2026, 5, 21),
        dry_run=False,
        **m,
    )
    # DB には残す
    m["db"].upsert_listing.assert_called_once()
    # Claude も DM も通知も触らない
    m["classifier"].classify.assert_not_called()
    m["dm_generator"].generate.assert_not_called()
    m["notifier"].post_listing.assert_not_called()
    m["sheets"].append_listing.assert_not_called()
    m["db"].insert_classification.assert_not_called()


def test_open_listing_runs_full_pipeline() -> None:
    listing = _make_listing(inquiry_closed=False)
    m = _mocks()
    process_listing(
        listing=listing,
        today=date(2026, 5, 21),
        dry_run=False,
        **m,
    )
    m["db"].upsert_listing.assert_called_once()
    m["classifier"].classify.assert_called_once()
    # priority=S なので DM 生成と通知も走る
    m["dm_generator"].generate.assert_called_once()
    m["notifier"].post_listing.assert_called_once()
    m["sheets"].append_listing.assert_called_once()
