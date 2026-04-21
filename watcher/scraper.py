"""Jimoty scraper.

Parsing strategy: Jimoty serves SSR HTML, but class names drift. We use a
best-effort approach — try several selectors, fall back to regex where useful.
Any field that cannot be parsed returns `None` and the classifier still runs;
the AI judge copes with partial data.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from datetime import date, datetime
from typing import Iterable

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
    def fetch_listing_page(self, keyword: str) -> list[Listing]:
        url = LISTING_URL_TEMPLATE.format(keyword=urllib.parse.quote(keyword))
        logger.info("fetching listing page: %s", url)
        resp = self.client.get(url)
        resp.raise_for_status()
        listings = list(self._parse_listing_html(resp.text))
        logger.info("parsed %d listings from listing page", len(listings))
        return listings

    def _parse_listing_html(self, html: str) -> Iterable[Listing]:
        tree = HTMLParser(html)

        # Jimoty listing cards are <li> or <div> that contain an <a href=".../article-xxxx">.
        seen_ids: set[str] = set()
        for anchor in tree.css("a[href*='/article-']"):
            href = anchor.attributes.get("href", "") or ""
            match = ARTICLE_ID_RE.search(href)
            if not match:
                continue
            article_id = match.group(0)
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)

            card = self._closest_card(anchor) or anchor
            url = href if href.startswith("http") else f"{JMTY_BASE}{href}"

            yield Listing(
                article_id=article_id,
                url=url,
                title=self._extract_title(card, anchor),
                price_yen=self._extract_price(card),
                prefecture=self._extract_prefecture(url),
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
        for sel in ("h2", "h3", ".p-articles-list-item-title", "[class*=title]"):
            node = card.css_first(sel)
            if node and node.text(strip=True):
                return node.text(strip=True)
        return (anchor.attributes.get("title") or anchor.text(strip=True) or "").strip()

    @staticmethod
    def _extract_price(card: Node) -> int | None:
        for sel in (".p-item-most-important", "[class*=price]", ".p-item-price"):
            node = card.css_first(sel)
            if not node:
                continue
            text = node.text(strip=True)
            if not text:
                continue
            if "応談" in text or "相談" in text:
                return None
            match = PRICE_RE.search(text.replace(",", ""))
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _extract_prefecture(url: str) -> str | None:
        # /okinawa/sale-... → 'okinawa'; we'll keep raw slug; classifier handles it.
        m = re.search(r"jmty\.jp/([^/]+)/", url)
        if not m:
            return None
        slug = m.group(1)
        return PREF_SLUG_TO_JA.get(slug, slug)

    @staticmethod
    def _extract_city(card: Node) -> str | None:
        for sel in ("[class*=area]", "[class*=location]", ".p-item-area"):
            node = card.css_first(sel)
            if node and node.text(strip=True):
                return node.text(strip=True)
        return None

    @staticmethod
    def _extract_category(card: Node) -> str | None:
        for sel in ("[class*=category]", "[class*=genre]"):
            node = card.css_first(sel)
            if node and node.text(strip=True):
                return node.text(strip=True)
        return None

    @staticmethod
    def _extract_thumb(card: Node) -> str | None:
        img = card.css_first("img")
        if not img:
            return None
        for attr in ("data-src", "data-original", "src"):
            val = img.attributes.get(attr)
            if val and val.startswith("http"):
                return val
        return None

    @staticmethod
    def _extract_snippet(card: Node) -> str | None:
        for sel in ("[class*=summary]", "[class*=description]", "p"):
            node = card.css_first(sel)
            if node:
                text = node.text(strip=True)
                if text and len(text) > 15:
                    return text[:300]
        return None

    @staticmethod
    def _extract_favorite_count(card: Node) -> int | None:
        for sel in ("[class*=favorite]", "[class*=like]"):
            node = card.css_first(sel)
            if not node:
                continue
            match = re.search(r"\d+", node.text(strip=True))
            if match:
                return int(match.group(0))
        return None

    # ------------------------------------------------------------------ detail
    def fetch_detail(self, listing: Listing) -> Listing:
        time.sleep(self.request_delay)
        logger.info("fetching detail: %s", listing.url)
        resp = self.client.get(listing.url)
        resp.raise_for_status()
        return self._parse_detail_html(listing, resp.text)

    def _parse_detail_html(self, listing: Listing, html: str) -> Listing:
        tree = HTMLParser(html)

        desc_node = (
            tree.css_first("[class*=description]")
            or tree.css_first(".p-articles-show__description")
            or tree.css_first("#js-article-description")
        )
        if desc_node:
            listing.description_full = desc_node.text(strip=True)[:8000]

        image_urls: list[str] = []
        for img in tree.css("img"):
            src = (
                img.attributes.get("data-src")
                or img.attributes.get("data-original")
                or img.attributes.get("src")
                or ""
            )
            if not src.startswith("http"):
                continue
            if "cdn.jmty" not in src and "jmty" not in src:
                continue
            if src in image_urls:
                continue
            image_urls.append(src)
            if len(image_urls) >= 5:
                break
        if image_urls:
            listing.image_urls = image_urls
            if not listing.thumbnail_url:
                listing.thumbnail_url = image_urls[0]

        for sel in ("[class*=user-name]", "[class*=seller]", "[class*=profile]"):
            node = tree.css_first(sel)
            if node and node.text(strip=True):
                listing.seller_name = node.text(strip=True)[:80]
                break

        text_all = tree.body.text(strip=True) if tree.body else ""
        if "事業者" in text_all or "法人" in text_all:
            listing.seller_type_hint = "business"
        elif "個人" in text_all:
            listing.seller_type_hint = "individual"

        listing.posted_date = self._parse_date(tree, ("投稿日", "登録日")) or listing.posted_date
        listing.last_updated_date = self._parse_date(tree, ("更新日",)) or listing.last_updated_date

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

        return listing

    @staticmethod
    def _parse_date(tree: HTMLParser, labels: tuple[str, ...]) -> date | None:
        text = tree.body.text() if tree.body else ""
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
