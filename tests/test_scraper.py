"""scraper.py の回帰テスト。

合成HTMLフィクスチャに対して動作することを確認する。
Jimoty本体HTMLが将来変わったらここのテストは落ちないが、
debug_scrape --from-html で実HTMLに対して走らせれば検知できる。
"""

from __future__ import annotations

from pathlib import Path

from watcher.models import Listing
from watcher.scraper import (
    JmtyScraper,
    _collect_listing_images,
    _is_useful_image_url,
)
from selectolax.parser import HTMLParser

FIXTURES = Path(__file__).parent / "fixtures"


def _scraper() -> JmtyScraper:
    return JmtyScraper(user_agent="test", request_delay_seconds=0)


def test_parse_listing_extracts_all_cards() -> None:
    html = (FIXTURES / "listing_sample.html").read_text(encoding="utf-8")
    s = _scraper()
    try:
        listings = list(s._parse_listing_html(html))
    finally:
        s.close()

    article_ids = [l.article_id for l in listings]
    assert "article-1o9e6w" in article_ids
    assert "article-1npme9" in article_ids
    assert "article-1be48t" in article_ids
    assert "article-1oh88t" in article_ids
    assert "article-1hx2f3" in article_ids
    assert len(listings) == 5


def test_parse_listing_extracts_fields() -> None:
    html = (FIXTURES / "listing_sample.html").read_text(encoding="utf-8")
    s = _scraper()
    try:
        listings = {l.article_id: l for l in s._parse_listing_html(html)}
    finally:
        s.close()

    okinawa = listings["article-1o9e6w"]
    assert okinawa.title and "6mトレーラーハウス" in okinawa.title
    assert okinawa.price_yen == 4_000_000
    assert okinawa.prefecture == "沖縄"
    assert okinawa.city == "うるま市"
    assert okinawa.category_label == "その他"
    assert okinawa.thumbnail_url and okinawa.thumbnail_url.startswith("https://img.cdn.jmty.jp/")
    assert okinawa.snippet and "780万" in okinawa.snippet
    assert okinawa.favorite_count == 42


def test_parse_listing_handles_zero_yen() -> None:
    html = (FIXTURES / "listing_sample.html").read_text(encoding="utf-8")
    s = _scraper()
    try:
        listings = {l.article_id: l for l in s._parse_listing_html(html)}
    finally:
        s.close()
    assert listings["article-1npme9"].price_yen == 0


def test_parse_listing_dedupes_article_ids() -> None:
    # 同じカードが二度出るHTML
    html = """
    <html><body>
      <a href="/x/sale-oth/article-aaaa"><h2>A</h2></a>
      <a href="/x/sale-oth/article-aaaa"><h2>A</h2></a>
      <a href="/x/sale-oth/article-bbbb"><h2>B</h2></a>
    </body></html>
    """
    s = _scraper()
    try:
        listings = list(s._parse_listing_html(html))
    finally:
        s.close()
    ids = [l.article_id for l in listings]
    assert ids == ["article-aaaa", "article-bbbb"]


def test_parse_detail_fills_description_and_dates() -> None:
    listing_html = (FIXTURES / "listing_sample.html").read_text(encoding="utf-8")
    detail_html = (FIXTURES / "detail_sample.html").read_text(encoding="utf-8")
    s = _scraper()
    try:
        listings = {l.article_id: l for l in s._parse_listing_html(listing_html)}
        target = listings["article-1o9e6w"]
        s._parse_detail_html(target, detail_html)
    finally:
        s.close()

    assert target.description_full and "780万円" in target.description_full
    assert target.posted_date is not None
    assert target.posted_date.year == 2026
    assert target.posted_date.month == 4
    assert target.posted_date.day == 7
    assert target.view_count == 3210
    assert target.seller_type_hint == "individual"
    assert target.seller_name and "沖縄太郎" in target.seller_name


def test_parse_detail_image_filtering_excludes_ads_and_avatars() -> None:
    detail_html = (FIXTURES / "detail_sample.html").read_text(encoding="utf-8")
    target = Listing(
        article_id="article-1o9e6w",
        url="",
        title="",
        price_yen=None,
        prefecture=None,
        city=None,
        category_label=None,
        thumbnail_url=None,
    )
    s = _scraper()
    try:
        s._parse_detail_html(target, detail_html)
    finally:
        s.close()

    assert len(target.image_urls) == 3
    for url in target.image_urls:
        assert "avatar" not in url
        assert "no_image" not in url
        assert "example.com" not in url
        assert url.startswith("https://img.cdn.jmty.jp/image/article-1o9e6w-")


def test_is_useful_image_url() -> None:
    assert _is_useful_image_url("https://img.cdn.jmty.jp/image/article-x-1.jpg")
    assert not _is_useful_image_url("")
    assert not _is_useful_image_url("https://example.com/x.jpg")
    assert not _is_useful_image_url("https://img.cdn.jmty.jp/avatar/u.png")
    assert not _is_useful_image_url("https://img.cdn.jmty.jp/no_image.jpg")
    assert not _is_useful_image_url("data:image/svg+xml,...")


def test_collect_listing_images_respects_limit() -> None:
    html = """
    <html><body>
      <img src="https://img.cdn.jmty.jp/image/a.jpg">
      <img src="https://img.cdn.jmty.jp/image/b.jpg">
      <img src="https://img.cdn.jmty.jp/image/c.jpg">
      <img src="https://img.cdn.jmty.jp/image/d.jpg">
    </body></html>
    """
    images = _collect_listing_images(HTMLParser(html), max_images=2)
    assert images == [
        "https://img.cdn.jmty.jp/image/a.jpg",
        "https://img.cdn.jmty.jp/image/b.jpg",
    ]
