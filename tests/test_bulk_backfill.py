"""bulk_backfill のクロール＋dedupe ロジック。"""

from __future__ import annotations

from dataclasses import dataclass, field

from watcher.bulk_backfill import crawl_all_pages, dedupe_keep_first
from watcher.models import Listing


def _lst(article_id: str, title: str = "") -> Listing:
    return Listing(
        article_id=article_id,
        url=f"https://jmty.jp/x/{article_id}",
        title=title or article_id,
        price_yen=1000,
        prefecture=None,
        city=None,
        category_label=None,
        thumbnail_url=None,
    )


@dataclass
class FakeScraper:
    pages_by_keyword: dict[str, list[list[Listing]]]
    calls: list[tuple[str, int]] = field(default_factory=list)

    def fetch_listing_page(self, keyword: str, page: int = 1) -> list[Listing]:
        self.calls.append((keyword, page))
        pages = self.pages_by_keyword.get(keyword, [])
        if page - 1 < len(pages):
            return pages[page - 1]
        return []


def test_crawl_all_pages_returns_unique_listings_across_pages() -> None:
    scraper = FakeScraper(
        pages_by_keyword={
            "kw": [
                [_lst("a"), _lst("b"), _lst("c")],
                [_lst("c"), _lst("d")],  # c は重複
                [_lst("e")],
                [],  # empty → 打ち切り
            ]
        }
    )
    out = crawl_all_pages(scraper, "kw", max_pages=10, delay_seconds=0)
    assert [lst.article_id for lst in out] == ["a", "b", "c", "d", "e"]


def test_crawl_stops_when_no_new_in_page() -> None:
    scraper = FakeScraper(
        pages_by_keyword={
            "kw": [
                [_lst("a"), _lst("b")],
                [_lst("a"), _lst("b")],  # 新規ゼロ → 打ち切り
                [_lst("c")],  # 到達しない
            ]
        }
    )
    out = crawl_all_pages(scraper, "kw", max_pages=10, delay_seconds=0)
    assert [lst.article_id for lst in out] == ["a", "b"]
    assert scraper.calls == [("kw", 1), ("kw", 2)]


def test_dedupe_keep_first_picks_first_occurrence_across_keywords() -> None:
    by_kw = {
        "kw1": [_lst("a", "tA-kw1"), _lst("b", "tB-kw1")],
        "kw2": [_lst("b", "tB-kw2"), _lst("c", "tC-kw2")],
    }
    merged = dedupe_keep_first(by_kw)
    assert set(merged.keys()) == {"a", "b", "c"}
    # b は kw1 の方が先に登場するのでそちらが残る
    assert merged["b"].title == "tB-kw1"


def test_dedupe_keep_first_empty_returns_empty() -> None:
    assert dedupe_keep_first({}) == {}
    assert dedupe_keep_first({"kw": []}) == {}
