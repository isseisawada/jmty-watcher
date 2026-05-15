"""Typed dataclasses shared across scraper / classifier / notifier."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


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

    def days_since_posted(self, today: date) -> int | None:
        if self.posted_date is None:
            return None
        return (today - self.posted_date).days

    def to_db_row(self) -> dict[str, Any]:
        row = asdict(self)
        for k in ("posted_date", "last_updated_date"):
            v = row.get(k)
            if v is not None:
                row[k] = v.isoformat()
        return row


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


@dataclass
class DmDraft:
    variant_polite: str
    variant_casual: str
    model_version: str
