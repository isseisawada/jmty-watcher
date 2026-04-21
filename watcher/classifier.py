"""Claude APIでジモティ出品を分類する。"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from anthropic import Anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .anthropic_utils import extract_json, fetch_image_blocks, load_prompt, render
from .models import Classification, Listing

logger = logging.getLogger(__name__)


VALID_PRIORITIES = {"S", "A", "B", "C"}
VALID_SELLER_TYPES = {"individual", "business", "unknown"}
VALID_CATEGORIES = {
    "residential",
    "commercial",
    "compact_utility",
    "container_modified",
    "self_built",
    "dilapidated",
    "unknown",
}
VALID_GRADES = {"A", "B", "C", "D"}


class Classifier:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.prompt_template = load_prompt("classifier")

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=16),
        retry=retry_if_exception_type(Exception),
    )
    def classify(self, listing: Listing, today: date | None = None) -> Classification:
        today = today or date.today()
        prompt = render(
            self.prompt_template,
            title=listing.title or "",
            price_yen=listing.price_yen if listing.price_yen is not None else "不明",
            prefecture=listing.prefecture or "",
            city=listing.city or "",
            category_label=listing.category_label or "",
            description_full=(listing.description_full or listing.snippet or "")[:4000],
            posted_date=listing.posted_date.isoformat() if listing.posted_date else "不明",
            days_since_posted=listing.days_since_posted(today) if listing.posted_date else "不明",
            favorite_count=listing.favorite_count if listing.favorite_count is not None else 0,
            seller_name=listing.seller_name or "",
            seller_type_hint=listing.seller_type_hint or "",
        )

        image_blocks = fetch_image_blocks(listing.image_urls or [], max_images=3)
        content: list[dict[str, Any]] = [*image_blocks, {"type": "text", "text": prompt}]

        logger.info("classifying listing=%s images=%d", listing.article_id, len(image_blocks))
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )

        text_parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
        text = "\n".join(text_parts)
        data = extract_json(text)
        return _parse_classification(data, self.model)


def _parse_classification(data: dict[str, Any], model_version: str) -> Classification:
    priority = str(data.get("priority", "C")).upper()
    if priority not in VALID_PRIORITIES:
        priority = "C"

    seller_type = str(data.get("seller_type", "unknown")).lower()
    if seller_type not in VALID_SELLER_TYPES:
        seller_type = "unknown"

    category = str(data.get("trailer_category", "unknown")).lower()
    if category not in VALID_CATEGORIES:
        category = "unknown"

    grade = str(data.get("condition_grade", "C")).upper()
    if grade not in VALID_GRADES:
        grade = "C"

    def _to_int(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    def _to_float(v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return Classification(
        is_actual_trailer_house=bool(data.get("is_actual_trailer_house", False)),
        seller_type=seller_type,
        trailer_category=category,
        estimated_market_price_yen=_to_int(data.get("estimated_market_price_yen")),
        price_gap_ratio=_to_float(data.get("price_gap_ratio")),
        condition_grade=grade,
        priority=priority,
        concerns=[str(c) for c in (data.get("concerns") or [])][:10],
        sales_pitch_hook=str(data.get("sales_pitch_hook", "") or "")[:300],
        model_version=model_version,
        raw_response=data,
    )
