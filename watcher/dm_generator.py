"""DM文（丁寧版／フランク版）をClaudeで生成する。"""

from __future__ import annotations

import logging
from datetime import date

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from .anthropic_utils import extract_json, load_prompt, render
from .models import Classification, DmDraft, Listing

logger = logging.getLogger(__name__)


class DmGenerator:
    def __init__(self, api_key: str, model: str, inquiry_url: str) -> None:
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.inquiry_url = inquiry_url
        self.prompt_template = load_prompt("dm_generator")

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=16))
    def generate(
        self,
        listing: Listing,
        classification: Classification,
        today: date | None = None,
    ) -> DmDraft:
        today = today or date.today()
        description_snippet = (listing.description_full or listing.snippet or "")[:600]
        prompt = render(
            self.prompt_template,
            title=listing.title or "",
            price_yen=listing.price_yen if listing.price_yen is not None else "不明",
            prefecture=listing.prefecture or "",
            city=listing.city or "",
            description_snippet=description_snippet,
            priority=classification.priority,
            estimated_market_price_yen=classification.estimated_market_price_yen or "不明",
            sales_pitch_hook=classification.sales_pitch_hook or "",
            days_since_posted=listing.days_since_posted(today) if listing.posted_date else "不明",
            seller_type=classification.seller_type,
            inquiry_url=self.inquiry_url,
        )

        logger.info("generating DM for listing=%s priority=%s", listing.article_id, classification.priority)
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        data = extract_json(text)

        polite = str((data.get("variant_polite") or {}).get("body") or "").strip()
        casual = str((data.get("variant_casual") or {}).get("body") or "").strip()
        if not polite and not casual:
            raise ValueError("DM generator returned empty bodies")

        return DmDraft(
            variant_polite=polite,
            variant_casual=casual,
            model_version=self.model,
        )
