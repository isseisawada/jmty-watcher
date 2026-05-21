"""DM バックフィルの target 列挙ロジックが正しいこと（DB はモック）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from watcher.backfill_dm import find_targets
from watcher.models import Classification, Listing


@dataclass
class FakeDb:
    """Db の必要なメソッドだけ実装したフェイク。"""

    listing_rows: list[dict[str, Any]]
    classifications_by_listing_id: dict[str, dict[str, Any]]
    listing_ids_with_dm: set[str]

    def list_all_listing_rows(self) -> list[dict[str, Any]]:
        return self.listing_rows

    def list_listing_ids_with_dm_draft(self) -> set[str]:
        return self.listing_ids_with_dm

    def get_latest_classification_row(self, listing_id: str) -> dict[str, Any] | None:
        return self.classifications_by_listing_id.get(listing_id)


def _listing_row(listing_id: str, article_id: str, title: str = "T") -> dict[str, Any]:
    return {
        "id": listing_id,
        "article_id": article_id,
        "url": f"https://jmty.jp/x/sale/{article_id}",
        "title": title,
        "price_yen": 1000,
        "prefecture": "千葉",
        "city": "柏",
        "category_label": None,
        "thumbnail_url": None,
        "description_full": "本文",
        "image_urls": [],
        "seller_name": None,
        "seller_type_hint": None,
        "seller_post_count": None,
        "posted_date": "2026-05-20",
        "last_updated_date": None,
        "view_count": None,
        "favorite_count": None,
    }


def _c_row(priority: str) -> dict[str, Any]:
    return {
        "is_actual_trailer_house": True,
        "seller_type": "individual",
        "trailer_category": "trailer_house",
        "estimated_market_price_yen": 1500,
        "price_gap_ratio": 0.5,
        "condition_grade": "good",
        "priority": priority,
        "concerns": [],
        "sales_pitch_hook": "test",
        "model_version": "claude-sonnet-4-6",
        "raw_response": None,
    }


def test_find_targets_filters_by_priority_and_existing_dm() -> None:
    db = FakeDb(
        listing_rows=[
            _listing_row("uuid-A", "article-A"),
            _listing_row("uuid-B", "article-B"),
            _listing_row("uuid-C", "article-C"),
            _listing_row("uuid-D", "article-D"),
            _listing_row("uuid-E", "article-E"),
        ],
        classifications_by_listing_id={
            "uuid-A": _c_row("S"),  # 対象（DMなし）
            "uuid-B": _c_row("A"),  # 対象外（既にDMあり）
            "uuid-C": _c_row("B"),  # 対象（DMなし）
            "uuid-D": _c_row("C"),  # 対象外（priority C）
            # uuid-E は分類なし → 対象外
        },
        listing_ids_with_dm={"uuid-B"},
    )

    targets = find_targets(db, priorities={"S", "A", "B"})
    article_ids = [t[1].article_id for t in targets]
    assert sorted(article_ids) == ["article-A", "article-C"]

    # 復元された型が正しい
    for listing_id, listing, classification in targets:
        assert isinstance(listing, Listing)
        assert isinstance(classification, Classification)
        assert listing.posted_date == date(2026, 5, 20)


def test_find_targets_respects_custom_priorities() -> None:
    db = FakeDb(
        listing_rows=[
            _listing_row("uuid-A", "article-A"),
            _listing_row("uuid-B", "article-B"),
        ],
        classifications_by_listing_id={
            "uuid-A": _c_row("S"),
            "uuid-B": _c_row("B"),
        },
        listing_ids_with_dm=set(),
    )

    # S/A だけ対象に絞ったら B は外れる
    targets = find_targets(db, priorities={"S", "A"})
    assert [t[1].article_id for t in targets] == ["article-A"]


def test_listing_from_db_row_handles_missing_optional_fields() -> None:
    row = {"id": "uuid-x", "article_id": "article-x"}  # 最小行
    listing = Listing.from_db_row(row)
    assert listing.article_id == "article-x"
    assert listing.title == ""
    assert listing.posted_date is None
    assert listing.image_urls == []
