"""Jimoty scraper.

実HTML構造の確認結果:
- **一覧ページ** は SSR HTML。`.p-articles-list-item` 配下に `.p-item-title` /
  `.p-item-most-important` / `.p-item-secondary-important` / `.p-item-supplementary-info`
  / `.p-item-detail` / `.p-item-history` 等の安定したクラス名が使われている。
- **詳細ページ** は React + styled-components で本文部の class 名が
  ハッシュ化されている (`sc-xxxx-y`)。代わりに `<script id="__NEXT_DATA__">` に
  全データが構造化JSONで埋め込まれているので、こちらをパースする。

そのため scraper は2系統に分けている:
- `_parse_listing_html`: HTMLセレクタベース
- `_parse_detail_from_next_data`: __NEXT_DATA__ JSON ベース（メイン）
- `_parse_detail_html`: NEXT_DATA が無い場合のHTMLフォールバック（互換用）
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from datetime import date, datetime
from typing import Any, Iterable

import httpx
from selectolax.parser import HTMLParser, Node

from .models import Listing

logger = logging.getLogger(__name__)

JMTY_BASE = "https://jmty.jp"
LISTING_URL_TEMPLATE = "https://jmty.jp/all/sale-kw-{keyword}"
ARTICLE_ID_RE = re.compile(r"article-[a-z0-9]+")
PRICE_RE = re.compile(r"([0-9][0-9,]*)")
DATE_TEXT_RE = re.compile(r"(\d{4})[/\-年]?(\d{1,2})[/\-月]?(\d{1,2})?")
JP_SHORT_DATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.DOTALL
)

# ジモティが出品の問い合わせを締め切ったときの本文マーカー。
# 例: https://jmty.jp/hokkaido/sale-oth/article-1jpqgf
_INQUIRY_CLOSED_MARKER = "お問い合わせの受付は終了いたしました"


class JmtyScraper:
    def __init__(
        self,
        user_agent: str,
        request_delay_seconds: float = 2.5,
        timeout: float = 20.0,
    ) -> None:
        self.request_delay = request_delay_seconds
        self.client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
            },
            timeout=timeout,
            follow_redirects=True,
        )

    def __enter__(self) -> "JmtyScraper":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.client.close()

    # ------------------------------------------------------------------ robots
    def check_robots_allowed(self, path: str = "/all/") -> bool:
        """Quick robots.txt check. Returns False only on explicit Disallow match."""
        try:
            resp = self.client.get(f"{JMTY_BASE}/robots.txt")
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("robots.txt fetch failed (%s) — proceeding conservatively", e)
            return True

        lines = [ln.strip() for ln in resp.text.splitlines()]
        in_star = False
        for ln in lines:
            if not ln or ln.startswith("#"):
                continue
            if ln.lower().startswith("user-agent:"):
                ua = ln.split(":", 1)[1].strip()
                in_star = ua == "*"
                continue
            if not in_star:
                continue
            if ln.lower().startswith("disallow:"):
                rule = ln.split(":", 1)[1].strip()
                if rule and path.startswith(rule):
                    logger.error("robots.txt disallows %s (rule: %s)", path, rule)
                    return False
        return True

    # ----------------------------------------------------------------- listing
    def fetch_listing_page(self, keyword: str, page: int = 1) -> list[Listing]:
        base = LISTING_URL_TEMPLATE.format(keyword=urllib.parse.quote(keyword))
        url = base if page <= 1 else f"{base}?page={page}"
        logger.info("fetching listing page: %s", url)
        resp = self.client.get(url)
        resp.raise_for_status()
        listings = list(self._parse_listing_html(resp.text))
        logger.info("parsed %d listings from listing page (page=%d)", len(listings), page)
        return listings

    def _parse_listing_html(self, html: str) -> Iterable[Listing]:
        tree = HTMLParser(html)

        seen_ids: set[str] = set()
        # 一覧カードは `<li class="p-articles-list-item">` に1件ずつ収まる。
        cards = tree.css("li.p-articles-list-item")
        if not cards:
            # フォールバック: 旧構造 or 違う一覧ページ形式
            cards = [self._closest_card(a) for a in tree.css("a[href*='/article-']")]

        for card in cards:
            if card is None:
                continue
            anchor = card.css_first("a[href*='/article-']")
            if anchor is None:
                continue
            href = anchor.attributes.get("href", "") or ""
            match = ARTICLE_ID_RE.search(href)
            if not match:
                continue
            article_id = match.group(0)
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)

            url = href if href.startswith("http") else f"{JMTY_BASE}{href}"

            yield Listing(
                article_id=article_id,
                url=url,
                title=self._extract_title(card, anchor),
                price_yen=self._extract_price(card),
                prefecture=self._extract_prefecture_from_card(card, url),
                city=self._extract_city(card),
                category_label=self._extract_category(card),
                thumbnail_url=self._extract_thumb(card),
                snippet=self._extract_snippet(card),
                favorite_count=self._extract_favorite_count(card),
            )

    @staticmethod
    def _closest_card(node: Node) -> Node | None:
        cur: Node | None = node
        for _ in range(6):
            if cur is None:
                return None
            parent = cur.parent
            if parent is None:
                return cur
            tag = (parent.tag or "").lower()
            if tag in ("li", "article") or (
                "class" in (parent.attributes or {})
                and "article" in (parent.attributes.get("class") or "").lower()
            ):
                return parent
            cur = parent
        return cur

    @staticmethod
    def _extract_title(card: Node, anchor: Node) -> str:
        title_div = card.css_first(".p-item-title")
        if title_div:
            text = title_div.text(strip=True)
            if text:
                return text
        # フォールバック
        return (anchor.attributes.get("title") or anchor.text(strip=True) or "").strip()

    @staticmethod
    def _extract_price(card: Node) -> int | None:
        node = card.css_first(".p-item-most-important")
        if not node:
            return None
        text = node.text(strip=True)
        if not text:
            return None
        if "応談" in text or "相談" in text:
            return None
        match = PRICE_RE.search(text.replace(",", ""))
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_prefecture_from_card(card: Node, url: str) -> str | None:
        node = card.css_first(".p-item-secondary-important")
        if node:
            text = node.text(strip=True)
            if text:
                return text
        # フォールバック: URL slug から
        m = re.search(r"jmty\.jp/([^/]+)/", url)
        if not m:
            return None
        slug = m.group(1)
        return PREF_SLUG_TO_JA.get(slug, slug)

    @staticmethod
    def _extract_city(card: Node) -> str | None:
        """
        .p-item-supplementary-info 内の最初の `<a>` が city。
        2番目以降は駅名やカテゴリで混在するので最初の1つだけ取る。
        """
        info_blocks = card.css(".p-item-supplementary-info")
        for info in info_blocks:
            anchors = info.css("a")
            for a in anchors:
                href = a.attributes.get("href", "") or ""
                # `a-XXXXX-name` パターンが city。`g-XXXX` はジャンル、`s-XXXX` は駅。
                if re.search(r"/a-\d+-", href):
                    text = a.text(strip=True)
                    if text:
                        return text
        return None

    @staticmethod
    def _extract_category(card: Node) -> str | None:
        """
        .p-item-supplementary-info 内の最後の `<a>` がカテゴリ（`/all/sale-toy` 等）。
        """
        for info in card.css(".p-item-supplementary-info"):
            anchors = info.css("a")
            for a in anchors:
                href = a.attributes.get("href", "") or ""
                if re.search(r"/all/sale-[a-z]+/?$", href):
                    text = a.text(strip=True)
                    if text:
                        return text
        return None

    @staticmethod
    def _extract_thumb(card: Node) -> str | None:
        img = card.css_first("img.p-item-image") or card.css_first("img")
        if not img:
            return None
        for attr in ("data-src", "data-original", "src"):
            val = img.attributes.get(attr)
            if val and val.startswith("http"):
                return val
        return None

    @staticmethod
    def _extract_snippet(card: Node) -> str | None:
        node = card.css_first(".p-item-detail")
        if node:
            text = node.text(strip=True)
            if text:
                return text[:300]
        return None

    @staticmethod
    def _extract_favorite_count(card: Node) -> int | None:
        # 一覧カードには通常お気に入り数は出ない。お気に入り数は詳細ページで取得。
        return None

    # ------------------------------------------------------------------ detail
    def fetch_detail(self, listing: Listing) -> Listing:
        time.sleep(self.request_delay)
        logger.info("fetching detail: %s", listing.url)
        resp = self.client.get(listing.url)
        resp.raise_for_status()
        return self.parse_detail(listing, resp.text)

    def parse_detail(self, listing: Listing, html: str) -> Listing:
        """__NEXT_DATA__ を最優先、無ければHTMLフォールバック。"""
        # 「お問い合わせの受付は終了いたしました」表示 → これ以降の分類・通知は不要。
        # NEXT_DATA / HTML 両方で最初に検出する（marker は静的なテキストなのでどちらでも拾える）。
        if _INQUIRY_CLOSED_MARKER in html:
            listing.inquiry_closed = True

        next_data = _extract_next_data(html)
        if next_data is not None:
            return _parse_detail_from_next_data(listing, next_data)
        logger.warning(
            "no __NEXT_DATA__ found for %s; falling back to HTML parsing",
            listing.article_id,
        )
        return self._parse_detail_html(listing, html)

    def _parse_detail_html(self, listing: Listing, html: str) -> Listing:
        tree = HTMLParser(html)

        # 詳細ページには「その他のお勧め」「関連の表示板」などで他出品が大量に並ぶ。
        # 同じ cdn.jmty.jp のサムネが混ざるため、まずメインの記事コンテナに絞る。
        main = _find_main_article_node(tree)

        desc_node = (
            main.css_first("[class*=description]")
            or main.css_first(".p-articles-show__description")
            or main.css_first("#js-article-description")
        )
        if desc_node:
            listing.description_full = desc_node.text(strip=True)[:8000]

        image_urls = _collect_listing_images(main, max_images=5)
        if image_urls:
            listing.image_urls = image_urls
            if not listing.thumbnail_url:
                listing.thumbnail_url = image_urls[0]

        for sel in ("[class*=user-name]", "[class*=seller]", "[class*=profile]"):
            node = main.css_first(sel)
            if node and node.text(strip=True):
                listing.seller_name = node.text(strip=True)[:80]
                break

        text_all = main.text(strip=True) or ""
        if "事業者" in text_all or "法人" in text_all:
            listing.seller_type_hint = "business"
        elif "個人" in text_all:
            listing.seller_type_hint = "individual"

        # 出品者の累計出品数。「投稿N件」「出品N件」のどちらかの表記。
        m = re.search(r"(?:投稿|出品)\s*(\d+)\s*件", text_all)
        if m:
            try:
                listing.seller_post_count = int(m.group(1))
            except ValueError:
                pass

        listing.posted_date = _parse_date_in(text_all, ("投稿日", "登録日")) or listing.posted_date
        listing.last_updated_date = (
            _parse_date_in(text_all, ("更新日",)) or listing.last_updated_date
        )

        # View count: heuristic — label like 「閲覧数」。
        m = re.search(r"閲覧\s*[:：]?\s*(\d[\d,]*)", text_all)
        if m:
            try:
                listing.view_count = int(m.group(1).replace(",", ""))
            except ValueError:
                pass

        # Favorite count (may be on detail page too)
        if listing.favorite_count is None:
            m = re.search(r"お気に入り\s*[:：]?\s*(\d+)", text_all)
            if m:
                listing.favorite_count = int(m.group(1))

        # 詳細ページに「ジャンル: その他/パーツ/家具/家電/おもちゃ」表示があれば、
        # 一覧で取れなかった場合のフォールバックに使う。
        # 隣接フィールドとテキストが連結するためホワイトリストで照合。
        if not listing.category_label:
            m = re.search(
                r"ジャンル\s*[:：]?\s*"
                r"(その他|パーツ|家具|家電|おもちゃ|スポーツ|楽器|本|"
                r"自転車|バイク|車|不動産|ペット用品|キッチン用品|工具)",
                text_all,
            )
            if m:
                listing.category_label = m.group(1)

        return listing

    @staticmethod
    def _parse_date(tree: HTMLParser, labels: tuple[str, ...]) -> date | None:
        text = tree.body.text() if tree.body else ""
        return _parse_date_in(text, labels)


# ===========================================================================
# 詳細ページ: __NEXT_DATA__ JSON ベース parsing
# ===========================================================================
def _extract_next_data(html: str) -> dict[str, Any] | None:
    """`<script id="__NEXT_DATA__">` の中身を JSON として返す。無ければ None。"""
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.warning("__NEXT_DATA__ JSON decode failed: %s", e)
        return None


def _parse_detail_from_next_data(listing: Listing, next_data: dict[str, Any]) -> Listing:
    """__NEXT_DATA__ の構造化データから Listing を埋める。"""
    try:
        page_props = next_data["props"]["pageProps"]
        results = page_props["articleResults"]
        article = results["article"]
    except (KeyError, TypeError) as e:
        logger.warning("__NEXT_DATA__ structure unexpected (%s); skipping", e)
        return listing

    if not listing.title:
        listing.title = article.get("title") or listing.title
    text = article.get("text") or ""
    if text:
        listing.description_full = text[:8000]

    par_items = article.get("par_category_items") or {}
    price = par_items.get("price")
    if isinstance(price, (int, float)) and listing.price_yen in (None, 0):
        listing.price_yen = int(price)

    fav = article.get("favorite_user_count")
    if isinstance(fav, int):
        listing.favorite_count = fav

    # categories
    large_genre = (article.get("large_genre") or {}).get("name")
    if large_genre and not listing.category_label:
        listing.category_label = large_genre

    # location: prefecture / city / town を組み立てる
    locations = article.get("locations") or []
    if locations:
        loc = locations[0]
        pref = (loc.get("prefecture") or {}).get("name")
        city = (loc.get("city") or {}).get("name_with_suffix") or (loc.get("city") or {}).get("name")
        town = (loc.get("town") or {}).get("name_with_suffix")
        if pref:
            listing.prefecture = pref
        if city:
            listing.city = f"{city}{town}" if town else city

    # images
    images = article.get("images") or []
    image_urls: list[str] = []
    for img in images[:5]:
        url = img.get("large_url") or img.get("medium_url") or img.get("small_url")
        if url:
            image_urls.append(url)
    if image_urls:
        listing.image_urls = image_urls
        if not listing.thumbnail_url:
            listing.thumbnail_url = image_urls[0]

    # dates
    created = article.get("created_at")
    updated = article.get("updated_at")
    if created:
        listing.posted_date = _parse_iso_date(created) or listing.posted_date
    if updated:
        listing.last_updated_date = _parse_iso_date(updated) or listing.last_updated_date

    # business フラグは決定的なので seller_type_hint に直接マップ
    business = article.get("business")
    if business is True:
        listing.seller_type_hint = "business"
    elif business is False:
        listing.seller_type_hint = "individual"

    # post_user 情報
    post_user = results.get("post_user") or {}
    if post_user:
        name = post_user.get("name")
        if name and not listing.seller_name:
            listing.seller_name = name[:80]
        count = post_user.get("articles_count")
        if isinstance(count, int):
            listing.seller_post_count = count
        # certification_status.business が True なら強い business シグナル
        cert = (post_user.get("certification_status") or {}).get("business")
        if cert is True:
            listing.seller_type_hint = "business"

    return listing


def _parse_iso_date(s: str) -> date | None:
    try:
        # "2026-05-17T18:51:34.838+09:00" のような ISO 形式
        return datetime.fromisoformat(s).date()
    except (ValueError, TypeError):
        return None


# 詳細ページの「メイン記事領域」を特定するためのセレクタ。
# Jimoty のHTMLは静的ファイルとして確認できていないので、候補を上から順に試す。
# 関連広告（aside / .p-related-* / .recommend / .other-articles 等）は除外したい。
_MAIN_ARTICLE_SELECTORS = (
    "article.p-articles-show",
    "[class*=p-articles-show]",
    "[id*=js-article]",
    "main article",
    "article",
    "main",
)


def _find_main_article_node(tree: HTMLParser):
    """メイン記事ノードを特定。見つからなければ body 全体を返す。"""
    for sel in _MAIN_ARTICLE_SELECTORS:
        node = tree.css_first(sel)
        if node is None:
            continue
        # 関連広告セクションそのものを誤って掴むケースを弾く
        cls = (node.attributes.get("class") or "").lower()
        if any(token in cls for token in ("related", "recommend", "other", "ads")):
            continue
        return node
    return tree.body if tree.body else tree


def _parse_date_in(text: str, labels: tuple[str, ...]) -> date | None:
    for label in labels:
        idx = text.find(label)
        if idx == -1:
            continue
        window = text[idx : idx + 40]
        m = DATE_TEXT_RE.search(window)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3) or "1"
            try:
                return date(int(y), int(mo), int(d))
            except ValueError:
                pass
        m2 = JP_SHORT_DATE_RE.search(window)
        if m2:
            mo, d = int(m2.group(1)), int(m2.group(2))
            today = datetime.now().date()
            year = today.year if mo <= today.month else today.year - 1
            try:
                return date(year, mo, d)
            except ValueError:
                pass
    return None


# 画像セレクタヘルパ。共有アバター・no_image プレースホルダ・SVG等は弾く。
_IMG_BLOCKLIST_TOKENS = (
    "no_image",
    "no-image",
    "noimage",
    "placeholder",
    "default",
    "avatar",
    "icon",
    "logo",
    ".svg",
)


def _is_useful_image_url(src: str) -> bool:
    if not src or not src.startswith("http"):
        return False
    lower = src.lower()
    if any(token in lower for token in _IMG_BLOCKLIST_TOKENS):
        return False
    if "jmty" not in lower:
        return False
    return True


def _collect_listing_images(root, max_images: int = 5) -> list[str]:
    """root の配下に限定して画像を収集する。

    詳細ページ全体に対して呼ぶと「その他のお勧め」の他出品サムネを拾ってしまうので、
    必ずメイン記事ノードに絞ってから呼び出すこと。
    """
    seen: set[str] = set()
    out: list[str] = []
    for img in root.css("img"):
        src = (
            img.attributes.get("data-src")
            or img.attributes.get("data-original")
            or img.attributes.get("src")
            or ""
        )
        if not _is_useful_image_url(src):
            continue
        if src in seen:
            continue
        seen.add(src)
        out.append(src)
        if len(out) >= max_images:
            break
    return out


# Rough prefecture slug → Japanese name. Jimoty uses these in URLs.
PREF_SLUG_TO_JA: dict[str, str] = {
    "hokkaido": "北海道",
    "aomori": "青森",
    "iwate": "岩手",
    "miyagi": "宮城",
    "akita": "秋田",
    "yamagata": "山形",
    "fukushima": "福島",
    "ibaraki": "茨城",
    "tochigi": "栃木",
    "gunma": "群馬",
    "saitama": "埼玉",
    "chiba": "千葉",
    "tokyo": "東京",
    "kanagawa": "神奈川",
    "niigata": "新潟",
    "toyama": "富山",
    "ishikawa": "石川",
    "fukui": "福井",
    "yamanashi": "山梨",
    "nagano": "長野",
    "gifu": "岐阜",
    "shizuoka": "静岡",
    "aichi": "愛知",
    "mie": "三重",
    "shiga": "滋賀",
    "kyoto": "京都",
    "osaka": "大阪",
    "hyogo": "兵庫",
    "nara": "奈良",
    "wakayama": "和歌山",
    "tottori": "鳥取",
    "shimane": "島根",
    "okayama": "岡山",
    "hiroshima": "広島",
    "yamaguchi": "山口",
    "tokushima": "徳島",
    "kagawa": "香川",
    "ehime": "愛媛",
    "kochi": "高知",
    "fukuoka": "福岡",
    "saga": "佐賀",
    "nagasaki": "長崎",
    "kumamoto": "熊本",
    "oita": "大分",
    "miyazaki": "宮崎",
    "kagoshima": "鹿児島",
    "okinawa": "沖縄",
}
