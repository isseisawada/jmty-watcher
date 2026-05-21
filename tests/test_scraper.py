"""scraper.py の回帰テスト。

合成HTMLフィクスチャに対して動作することを確認する。
Jimoty本体HTMLが将来変わったらここのテストは落ちないが、
debug_scrape --from-html で実HTMLに対して走らせれば検知できる。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from selectolax.parser import HTMLParser

from watcher.models import Listing
from watcher.scraper import (
    JmtyScraper,
    _collect_listing_images,
    _is_useful_image_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
REAL_HTML_DIR = Path(__file__).resolve().parent.parent / "debug_cache"


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
    assert okinawa.thumbnail_url and okinawa.thumbnail_url.startswith("https://cdn.jmty.jp/")
    assert okinawa.snippet and "780万" in okinawa.snippet
    # favorite_count は一覧カードには出ないので詳細から拾う（ここでは None で正しい）


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
    <html><body><ul>
      <li class="p-articles-list-item">
        <a class="p-item-image-link" href="/x/sale-oth/article-aaaa">
          <img class="p-item-image" src="https://cdn.jmty.jp/articles/images/x/thumb_m.jpg">
        </a>
        <div class="p-item-title"><a href="/x/sale-oth/article-aaaa">A</a></div>
      </li>
      <li class="p-articles-list-item">
        <a class="p-item-image-link" href="/x/sale-oth/article-aaaa">
          <img class="p-item-image" src="https://cdn.jmty.jp/articles/images/x/thumb_m.jpg">
        </a>
        <div class="p-item-title"><a href="/x/sale-oth/article-aaaa">A</a></div>
      </li>
      <li class="p-articles-list-item">
        <a class="p-item-image-link" href="/x/sale-oth/article-bbbb">
          <img class="p-item-image" src="https://cdn.jmty.jp/articles/images/y/thumb_m.jpg">
        </a>
        <div class="p-item-title"><a href="/x/sale-oth/article-bbbb">B</a></div>
      </li>
    </ul></body></html>
    """
    s = _scraper()
    try:
        listings = list(s._parse_listing_html(html))
    finally:
        s.close()
    ids = [l.article_id for l in listings]
    assert ids == ["article-aaaa", "article-bbbb"]


def test_parse_detail_sets_inquiry_closed_when_marker_present() -> None:
    html = (
        "<html><body>"
        "<article class='p-articles-show'>"
        "<h1>テストトレーラーハウス</h1>"
        "<div>本文</div>"
        "<div>お問い合わせの受付は終了いたしました</div>"
        "</article></body></html>"
    )
    target = Listing(
        article_id="article-closed",
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
        s.parse_detail(target, html)
    finally:
        s.close()
    assert target.inquiry_closed is True


def test_parse_detail_inquiry_closed_default_false() -> None:
    """マーカーが無ければ inquiry_closed は False のまま。"""
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
        s.parse_detail(target, detail_html)
    finally:
        s.close()
    assert target.inquiry_closed is False


def test_parse_detail_next_data_article_closed_flag_sets_inquiry_closed() -> None:
    """__NEXT_DATA__ の article.closed: True で inquiry_closed が True になる。

    実環境では「お問い合わせの受付は終了いたしました」は React レンダリングで
    HTML 本文に現れないため、NEXT_DATA の article.closed を見るのが正解。
    """
    import json

    next_data = {
        "props": {
            "pageProps": {
                "articleResults": {
                    "article": {
                        "title": "古いトレーラーハウス",
                        "text": "本文",
                        "closed": True,
                        "par_category_items": {"price": 100000},
                        "favorite_user_count": 1,
                        "images": [],
                        "locations": [],
                        "created_at": "2025-09-08T11:30:01+09:00",
                        "updated_at": "2025-09-09T10:15:27+09:00",
                        "business": False,
                    },
                    "post_user": {},
                }
            }
        }
    }
    html = (
        f'<html><head><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data)}</script></head><body></body></html>"
    )
    target = Listing(
        article_id="article-1jpqgf",
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
        s.parse_detail(target, html)
    finally:
        s.close()
    assert target.inquiry_closed is True


def test_parse_detail_next_data_article_closed_false_keeps_open() -> None:
    import json

    next_data = {
        "props": {
            "pageProps": {
                "articleResults": {
                    "article": {
                        "title": "現役トレーラーハウス",
                        "text": "本文",
                        "closed": False,
                        "par_category_items": {"price": 1000000},
                        "favorite_user_count": 0,
                        "images": [],
                        "locations": [],
                        "business": False,
                    },
                    "post_user": {},
                }
            }
        }
    }
    html = (
        f'<html><body><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data)}</script></body></html>"
    )
    target = Listing(
        article_id="article-x",
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
        s.parse_detail(target, html)
    finally:
        s.close()
    assert target.inquiry_closed is False


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
    assert target.seller_post_count == 1


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


def test_parse_detail_fills_category_when_missing() -> None:
    """一覧でカテゴリが取れなかった場合、詳細の『ジャンル: ...』からフォールバックする。"""
    detail_html = (FIXTURES / "detail_sample.html").read_text(encoding="utf-8")
    target = Listing(
        article_id="article-1o9e6w",
        url="",
        title="",
        price_yen=None,
        prefecture=None,
        city=None,
        category_label=None,  # ← 一覧で取れていない状態
        thumbnail_url=None,
    )
    s = _scraper()
    try:
        s._parse_detail_html(target, detail_html)
    finally:
        s.close()
    assert target.category_label == "その他"


def test_parse_detail_ignores_related_ads_with_jmty_cdn_thumbs() -> None:
    """関連広告セクション内の cdn.jmty.jp 画像/テキストを本体に混入させない。"""
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

    # 関連広告の画像が混ざっていないこと
    for url in target.image_urls:
        assert "airpods" not in url.lower()
        assert "pet" not in url.lower()
        assert "toy" not in url.lower()
        assert "bike" not in url.lower()

    # description に関連広告のテキストが混入していないこと
    desc = target.description_full or ""
    assert "AirPods" not in desc
    assert "ガチャ" not in desc

    # seller_type_hint は本体の「個人出品」を優先（関連広告の「事業者出品」/「法人出品」を拾わない）
    assert target.seller_type_hint == "individual"


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


# ===========================================================================
# 実HTMLでの回帰テスト（debug_cache/ にコミット済みのサンプル）
# ===========================================================================


def _real_html_available() -> bool:
    return (REAL_HTML_DIR / "listing.html").exists()


@pytest.mark.skipif(not _real_html_available(), reason="debug_cache/ が存在しない")
def test_real_listing_html_extracts_30_listings() -> None:
    html = (REAL_HTML_DIR / "listing.html").read_text(encoding="utf-8")
    s = _scraper()
    try:
        listings = list(s._parse_listing_html(html))
    finally:
        s.close()
    assert len(listings) >= 25, f"30件取れるべきところ {len(listings)}件"

    # 全件 title / prefecture / thumbnail が埋まっていること
    miss_title = sum(1 for l in listings if not l.title)
    miss_pref = sum(1 for l in listings if not l.prefecture)
    miss_city = sum(1 for l in listings if not l.city)
    miss_thumb = sum(1 for l in listings if not l.thumbnail_url)
    miss_snippet = sum(1 for l in listings if not l.snippet)
    total = len(listings)

    assert miss_title == 0, f"title欠損 {miss_title}/{total}"
    assert miss_pref == 0, f"prefecture欠損 {miss_pref}/{total}"
    assert miss_city / total <= 0.1, f"city欠損率 {miss_city}/{total}"
    assert miss_thumb == 0, f"thumbnail欠損 {miss_thumb}/{total}"
    assert miss_snippet / total <= 0.1, f"snippet欠損率 {miss_snippet}/{total}"


@pytest.mark.skipif(not _real_html_available(), reason="debug_cache/ が存在しない")
def test_real_detail_html_extracts_full_data() -> None:
    detail_html = (REAL_HTML_DIR / "article-1oh88t.html").read_text(encoding="utf-8")
    target = Listing(
        article_id="article-1oh88t",
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
        s.parse_detail(target, detail_html)
    finally:
        s.close()

    # __NEXT_DATA__ から取れた本物のデータ
    assert target.title and "レゴ" in target.title
    assert target.description_full and len(target.description_full) > 100
    assert target.image_urls and len(target.image_urls) >= 3
    assert target.posted_date is not None
    assert target.seller_type_hint == "individual"
    assert target.seller_name == "みどり"
    assert target.seller_post_count == 56
    assert target.price_yen == 1800
    assert target.prefecture == "沖縄"


@pytest.mark.skipif(not _real_html_available(), reason="debug_cache/ が存在しない")
def test_real_detail_business_flag() -> None:
    """business=True の出品は seller_type_hint='business' になる。"""
    detail_html = (REAL_HTML_DIR / "article-p400e.html").read_text(encoding="utf-8")
    target = Listing(
        article_id="article-p400e",
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
        s.parse_detail(target, detail_html)
    finally:
        s.close()
    assert target.seller_type_hint == "business"
    assert target.seller_post_count is not None and target.seller_post_count >= 1
