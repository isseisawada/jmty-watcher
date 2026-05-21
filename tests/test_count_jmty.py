"""count_keyword のページネーション打ち切りロジックを担保する。"""

from __future__ import annotations

from dataclasses import dataclass, field

from watcher.count_jmty import count_keyword
from watcher.models import Listing


def _lst(article_id: str) -> Listing:
    return Listing(
        article_id=article_id,
        url=f"https://jmty.jp/x/{article_id}",
        title=article_id,
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


def test_stops_when_no_new_article_ids_added() -> None:
    # page 1: A,B,C / page 2: A,B,C （新規ゼロ）→ 2 ページで打ち切り
    scraper = FakeScraper(
        pages_by_keyword={
            "kw": [
                [_lst("art-A"), _lst("art-B"), _lst("art-C")],
                [_lst("art-A"), _lst("art-B"), _lst("art-C")],
                [_lst("art-D")],  # ここまで到達しないこと
            ]
        }
    )
    count, last_page = count_keyword(scraper, "kw", max_pages=10, delay_seconds=0)
    assert count == 3
    assert last_page == 2
    assert scraper.calls == [("kw", 1), ("kw", 2)]


def test_stops_on_empty_page() -> None:
    scraper = FakeScraper(
        pages_by_keyword={
            "kw": [
                [_lst("a"), _lst("b")],
                [_lst("c")],
                [],  # 空 → 打ち切り
            ]
        }
    )
    count, last_page = count_keyword(scraper, "kw", max_pages=10, delay_seconds=0)
    assert count == 3
    assert last_page == 3


def test_respects_max_pages() -> None:
    # 毎ページ新規が増え続けるケースで max_pages で必ず止まる
    scraper = FakeScraper(
        pages_by_keyword={
            "kw": [[_lst(f"art-{i*10+j}") for j in range(10)] for i in range(5)]
        }
    )
    count, last_page = count_keyword(scraper, "kw", max_pages=3, delay_seconds=0)
    assert count == 30
    assert last_page == 3
    assert len(scraper.calls) == 3


def test_handles_fetch_exception() -> None:
    class Boom(FakeScraper):
        def fetch_listing_page(self, keyword: str, page: int = 1) -> list[Listing]:
            self.calls.append((keyword, page))
            if page == 2:
                raise RuntimeError("network down")
            return [_lst(f"a{page}")]

    scraper = Boom(pages_by_keyword={})
    count, last_page = count_keyword(scraper, "kw", max_pages=10, delay_seconds=0)
    assert count == 1
    assert last_page == 2  # 例外が出たページ番号
