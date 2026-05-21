"""Typed dataclasses shared across scraper / classifier / notifier."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass
class Listing:
    """A scraped Jimoty listing. Fields below `snippet` are filled from the detail page."""

    article_id: str
    url: str
    title: str
    price_yen: int | None
    prefecture: str | None
    city: str | None
    category_label: str | None
    thumbnail_url: str | None
    snippet: str | None = None
    created_at_text: str | None = None
    updated_at_text: str | None = None
    favorite_count: int | None = None

    # Detail page
    description_full: str | None = None
    image_urls: list[str] = field(default_factory=list)
    seller_name: str | None = None
    seller_type_hint: str | None = None
    seller_post_count: int | None = None  # この出品者の累計出品数（個人/業者判定の強シグナル）
    posted_date: date | None = None
    last_updated_date: date | None = None
    view_count: int | None = None
    inquiry_closed: bool = False  # ジモティ側で「お問い合わせの受付は終了いたしました」表示の出品

    def days_since_posted(self, today: date) -> int | None:
        if self.posted_date is None:
            return None
        return (today - self.posted_date).days

    def to_db_row(self) -> dict[str, Any]:
        row = asdict(self)
        # jmty_listings スキーマに存在しない一時フィールド（一覧ページ生テキスト等）は落とす。
        # これらは詳細パース時により正確な値（posted_date 等）に置き換わるためDB保存不要。
        for k in ("snippet", "created_at_text", "updated_at_text"):
            row.pop(k, None)
        for k in ("posted_date", "last_updated_date"):
            v = row.get(k)
            if v is not None:
                row[k] = v.isoformat()
        return row

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "Listing":
        """Supabase の jmty_listings 行から復元（バックフィル等で使用）。"""
        return cls(
            article_id=row["article_id"],
            url=row.get("url") or "",
            title=row.get("title") or "",
            price_yen=row.get("price_yen"),
            prefecture=row.get("prefecture"),
            city=row.get("city"),
            category_label=row.get("category_label"),
            thumbnail_url=row.get("thumbnail_url"),
            description_full=row.get("description_full"),
            image_urls=list(row.get("image_urls") or []),
            seller_name=row.get("seller_name"),
            seller_type_hint=row.get("seller_type_hint"),
            seller_post_count=row.get("seller_post_count"),
            posted_date=_parse_iso_date(row.get("posted_date")),
            last_updated_date=_parse_iso_date(row.get("last_updated_date")),
            view_count=row.get("view_count"),
            favorite_count=row.get("favorite_count"),
            inquiry_closed=bool(row.get("inquiry_closed")),
        )


@dataclass
class Classification:
    is_actual_trailer_house: bool
    seller_type: str
    trailer_category: str
    estimated_market_price_yen: int | None
    price_gap_ratio: float | None
    condition_grade: str
    priority: str  # S | A | B | C
    concerns: list[str]
    sales_pitch_hook: str
    model_version: str
    raw_response: dict[str, Any] | None = None

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "Classification":
        return cls(
            is_actual_trailer_house=bool(row.get("is_actual_trailer_house")),
            seller_type=row.get("seller_type") or "",
            trailer_category=row.get("trailer_category") or "",
            estimated_market_price_yen=row.get("estimated_market_price_yen"),
            price_gap_ratio=float(row["price_gap_ratio"])
            if row.get("price_gap_ratio") is not None
            else None,
            condition_grade=row.get("condition_grade") or "",
            priority=row.get("priority") or "",
            concerns=list(row.get("concerns") or []),
            sales_pitch_hook=row.get("sales_pitch_hook") or "",
            model_version=row.get("model_version") or "",
            raw_response=row.get("raw_response"),
        )


@dataclass
class DmDraft:
    variant_polite: str
    variant_casual: str
    model_version: str
