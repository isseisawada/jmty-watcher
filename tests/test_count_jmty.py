"""count_keyword / probe_closed の挙動を担保する。"""

from __future__ import annotations

from dataclasses import dataclass, field

from watcher.count_jmty import count_keyword, probe_closed
from watcher.models import Listing


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


@dataclass
class FakeScraper:
    pages_by_keyword: dict[str, list[list[Listing]]] = field(default_factory=dict)
    closed_ids: set[str] = field(default_factory=set)
    fail_ids: set[str] = field(default_factory=set)
    list_calls: list[tuple[str, int]] = field(default_factory=list)
    detail_calls: list[str] = field(default_factory=list)

    def fetch_listing_page(self, keyword: str, page: int = 1) -> list[Listing]:
        self.list_calls.append((keyword, page))
        pages = self.pages_by_keyword.get(keyword, [])
        if page - 1 < len(pages):
            return pages[page - 1]
        return []

    def fetch_detail(self, listing: Listing) -> Listing:
        self.detail_calls.append(listing.article_id)
        if listing.article_id in self.fail_ids:
            raise RuntimeError("boom")
        if listing.article_id in self.closed_ids:
            listing.inquiry_closed = True
        return listing


def test_count_keyword_stops_when_no_new_added() -> None:
    scraper = FakeScraper(
        pages_by_keyword={
            "kw": [
                [_lst("a"), _lst("b"), _lst("c")],
                [_lst("a"), _lst("b"), _lst("c")],  # 新規ゼロ → 打ち切り
                [_lst("d")],  # 到達しない
            ]
        }
    )
    listings, last_page = count_keyword(
        scraper, "kw", max_pages=10, delay_seconds=0
    )
    assert [lst.article_id for lst in listings] == ["a", "b", "c"]
    assert last_page == 2


def test_count_keyword_stops_on_empty_page() -> None:
    scraper = FakeScraper(
        pages_by_keyword={"kw": [[_lst("a"), _lst("b")], [_lst("c")], []]}
    )
    listings, _ = count_keyword(scraper, "kw", max_pages=10, delay_seconds=0)
    assert [lst.article_id for lst in listings] == ["a", "b", "c"]


def test_count_keyword_respects_max_pages() -> None:
    scraper = FakeScraper(
        pages_by_keyword={
            "kw": [[_lst(f"a{i*10+j}") for j in range(10)] for i in range(5)]
        }
    )
    listings, last_page = count_keyword(scraper, "kw", max_pages=3, delay_seconds=0)
    assert len(listings) == 30
    assert last_page == 3


def test_count_keyword_handles_fetch_exception() -> None:
    class Boom(FakeScraper):
        def fetch_listing_page(self, keyword: str, page: int = 1) -> list[Listing]:
            self.list_calls.append((keyword, page))
            if page == 2:
                raise RuntimeError("network down")
            return [_lst(f"a{page}")]

    scraper = Boom()
    listings, last_page = count_keyword(scraper, "kw", max_pages=10, delay_seconds=0)
    assert [lst.article_id for lst in listings] == ["a1"]
    assert last_page == 2


def test_probe_closed_counts_open_and_closed() -> None:
    listings = [_lst("a"), _lst("b"), _lst("c"), _lst("d")]
    scraper = FakeScraper(closed_ids={"b", "d"})
    open_n, closed_n, closed_ids = probe_closed(
        scraper, listings, delay_seconds=0
    )
    assert open_n == 2
    assert closed_n == 2
    assert sorted(closed_ids) == ["b", "d"]
    # 全件 fetch されたこと
    assert scraper.detail_calls == ["a", "b", "c", "d"]


def test_probe_closed_skips_failed_detail_fetches() -> None:
    listings = [_lst("a"), _lst("b"), _lst("c")]
    scraper = FakeScraper(closed_ids={"a"}, fail_ids={"b"})
    open_n, closed_n, closed_ids = probe_closed(
        scraper, listings, delay_seconds=0
    )
    # a: closed, b: fail (どちらにもカウントしない), c: open
    assert open_n == 1
    assert closed_n == 1
    assert closed_ids == ["a"]
