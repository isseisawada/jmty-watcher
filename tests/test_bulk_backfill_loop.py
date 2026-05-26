"""bulk_backfill.main の --max-classify が Sheets 追加件数の上限として
正しく機能することを担保する。受付終了済み (closed) と priority=C は
カウントせず、S/A/B でのみ +1 して停止条件を満たす。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from unittest.mock import patch

import watcher.bulk_backfill as bb
from watcher.models import Classification, Listing


def _lst(article_id: str, *, closed: bool = False) -> Listing:
    return Listing(
        article_id=article_id,
        url=f"https://jmty.jp/x/{article_id}",
        title=article_id,
        price_yen=1000,
        prefecture=None,
        city=None,
        category_label=None,
        thumbnail_url=None,
        inquiry_closed=closed,
    )


def _cls(priority: str) -> Classification:
    return Classification(
        is_actual_trailer_house=priority != "C",
        seller_type="individual",
        trailer_category="residential" if priority != "C" else "unknown",
        estimated_market_price_yen=1500,
        price_gap_ratio=0.5,
        condition_grade="A",
        priority=priority,
        concerns=[],
        sales_pitch_hook="",
        model_version="x",
    )


@dataclass
class FakeScraper:
    crawl_results: dict[str, list[list[Listing]]] = field(default_factory=dict)
    closed_marker_ids: set[str] = field(default_factory=set)
    detail_calls: list[str] = field(default_factory=list)
    list_calls: list[tuple[str, int]] = field(default_factory=list)

    # context manager / scraper API
    def __enter__(self) -> "FakeScraper":
        return self

    def __exit__(self, *a: object) -> None:
        pass

    def close(self) -> None:
        pass

    def check_robots_allowed(self) -> bool:
        return True

    def fetch_listing_page(self, keyword: str, page: int = 1) -> list[Listing]:
        self.list_calls.append((keyword, page))
        pages = self.crawl_results.get(keyword, [])
        if page - 1 < len(pages):
            return pages[page - 1]
        return []

    def fetch_detail(self, listing: Listing) -> Listing:
        self.detail_calls.append(listing.article_id)
        if listing.article_id in self.closed_marker_ids:
            listing.inquiry_closed = True
        return listing


@dataclass
class FakeDb:
    existing_ids: set[str] = field(default_factory=set)
    upserted: list[str] = field(default_factory=list)
    classifications: list[tuple[str, Classification]] = field(default_factory=list)

    def list_existing_article_ids(self) -> set[str]:
        return self.existing_ids

    def upsert_listing(self, listing: Listing) -> str:
        self.upserted.append(listing.article_id)
        return f"uuid-{listing.article_id}"

    def insert_classification(self, lid: str, c: Classification) -> str:
        self.classifications.append((lid, c))
        return f"cuuid-{lid}"

    def upsert_dm_draft(self, *_a: object, **_k: object) -> None:
        pass

    def log_outreach_pending(self, **_k: object) -> str:
        return "ouuid"


@dataclass
class FakeSheets:
    calls: list[str] = field(default_factory=list)

    def append_listing(
        self, *, listing: Listing, classification: Classification, **_k: object
    ) -> bool:
        self.calls.append(listing.article_id)
        return True

    def close(self) -> None:
        pass


def _run_bulk_backfill(
    *,
    new_articles: list[str],
    closed_ids: set[str],
    priorities_by_article: dict[str, str],
    max_classify: int | None,
) -> tuple[FakeSheets, FakeDb, int]:
    """bulk_backfill.main を mock 経由で実行し、Sheets 呼び出しと終了コードを返す。"""

    new_listings = [_lst(aid) for aid in new_articles]
    scraper = FakeScraper(
        crawl_results={"kw": [new_listings, []]},  # 1ページ目に全部、2ページ目空で打ち切り
        closed_marker_ids=closed_ids,
    )
    db = FakeDb()
    sheets = FakeSheets()

    cfg = type(
        "Cfg",
        (),
        dict(
            anthropic_api_key="x",
            classifier_model="x",
            dm_model="x",
            supabase_url="x",
            supabase_key="x",
            slack_bot_token=None,
            slack_channel_id=None,
            sheets_webhook_url="https://x/exec",
            sheets_webhook_token="t",
            sheets_view_url=None,
            search_keywords=("kw",),
            max_details_per_run=30,
            request_delay_seconds=0,
            dry_run=False,
            http_timeout_seconds=20.0,
            user_agent="ua",
            yadokari_inquiry_url="https://x",
        ),
    )()

    def classify_side_effect(listing: Listing, *, today: date) -> Classification:
        return _cls(priorities_by_article[listing.article_id])

    args = argparse.Namespace(
        keywords="kw",
        max_pages=20,
        max_classify=max_classify,
        dry_run=False,
    )

    with (
        patch.object(bb, "load_config", return_value=cfg),
        patch.object(bb, "Db", return_value=db),
        patch.object(bb, "JmtyScraper", return_value=scraper),
        patch.object(bb, "SheetsNotifier", return_value=sheets),
        patch.object(bb, "Classifier") as classifier_cls,
        patch.object(bb, "DmGenerator") as dm_cls,
        patch("argparse.ArgumentParser.parse_args", return_value=args),
    ):
        classifier_cls.return_value.classify.side_effect = classify_side_effect
        dm_cls.return_value.generate.return_value = type(
            "Draft", (), dict(variant_polite="full body", model_version="x")
        )
        rc = bb.main([])

    return sheets, db, rc


def test_max_classify_counts_only_sheets_additions() -> None:
    """closed と priority=C はカウントせず、S/A/B のみで N に達するまで進む。"""
    sheets, _db, rc = _run_bulk_backfill(
        new_articles=["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9"],
        closed_ids={"a1", "a2", "a4"},  # 3件 closed
        priorities_by_article={
            "a3": "C",  # non-trailer
            "a5": "C",
            "a6": "B",  # ← 1件目の add
            "a7": "C",
            "a8": "A",  # ← 2件目の add
            "a9": "S",  # 到達しない（target=2 で stop）
        },
        max_classify=2,
    )
    assert rc == 0
    # Sheets に追加されたのは a6, a8 の2件のみ
    assert sheets.calls == ["a6", "a8"]


def test_max_classify_none_processes_all() -> None:
    """--max-classify 未指定なら全件処理。"""
    sheets, _db, rc = _run_bulk_backfill(
        new_articles=["x1", "x2", "x3"],
        closed_ids=set(),
        priorities_by_article={"x1": "S", "x2": "C", "x3": "A"},
        max_classify=None,
    )
    assert rc == 0
    # priority C 以外（x1, x3）が Sheets に入る
    assert sheets.calls == ["x1", "x3"]


def test_all_closed_does_not_hang() -> None:
    """全件 closed でもループは尽きて終了する（無限ループしない）。"""
    sheets, _db, rc = _run_bulk_backfill(
        new_articles=["c1", "c2", "c3"],
        closed_ids={"c1", "c2", "c3"},
        priorities_by_article={},
        max_classify=5,
    )
    assert rc == 0
    assert sheets.calls == []
