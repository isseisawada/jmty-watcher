"""Sheets バックフィルの target 列挙が priority フィルタを効かせること。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from watcher.backfill_sheets import find_targets


@dataclass
class FakeDb:
    listing_rows: list[dict[str, Any]]
    classifications_by_listing_id: dict[str, dict[str, Any]]

    def list_all_listing_rows(self) -> list[dict[str, Any]]:
        return self.listing_rows

    def get_latest_classification_row(self, listing_id: str) -> dict[str, Any] | None:
        return self.classifications_by_listing_id.get(listing_id)


def _row(listing_id: str, article_id: str) -> dict[str, Any]:
    return {
        "id": listing_id,
        "article_id": article_id,
        "url": f"https://jmty.jp/x/sale/{article_id}",
        "title": "T",
        "thumbnail_url": "https://img.cdn.jmty.jp/x.jpg",
        "image_urls": [],
    }


def _cls(priority: str) -> dict[str, Any]:
    return {
        "is_actual_trailer_house": True,
        "seller_type": "individual",
        "trailer_category": "trailer_house",
        "estimated_market_price_yen": 1000,
        "price_gap_ratio": 0.0,
        "condition_grade": "good",
        "priority": priority,
        "concerns": [],
        "sales_pitch_hook": "",
        "model_version": "x",
    }


def test_find_targets_keeps_only_notify_priorities() -> None:
    db = FakeDb(
        listing_rows=[
            _row("uuid-S", "art-S"),
            _row("uuid-A", "art-A"),
            _row("uuid-B", "art-B"),
            _row("uuid-C", "art-C"),
            _row("uuid-N", "art-N"),  # 分類なし
        ],
        classifications_by_listing_id={
            "uuid-S": _cls("S"),
            "uuid-A": _cls("A"),
            "uuid-B": _cls("B"),
            "uuid-C": _cls("C"),
        },
    )
    targets = find_targets(db, priorities={"S", "A", "B"})
    article_ids = sorted(t[0].article_id for t in targets)
    assert article_ids == ["art-A", "art-B", "art-S"]


def test_find_targets_with_restricted_priorities() -> None:
    db = FakeDb(
        listing_rows=[_row("uuid-1", "art-1"), _row("uuid-2", "art-2")],
        classifications_by_listing_id={
            "uuid-1": _cls("S"),
            "uuid-2": _cls("B"),
        },
    )
    targets = find_targets(db, priorities={"S"})
    assert [t[0].article_id for t in targets] == ["art-1"]
