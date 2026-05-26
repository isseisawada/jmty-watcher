"""DM文（1パターン・丁寧版）を Claude で生成する。

ヘッダーとフッターは下記の定数で固定。
Claude には中段4段落のみを生成させ、コード側でサンドイッチして
完成本文を返す。
"""

from __future__ import annotations

import logging
from datetime import date

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from .anthropic_utils import extract_json, load_prompt, render
from .models import Classification, DmDraft, Listing

logger = logging.getLogger(__name__)


DM_HEADER = (
    "はじめまして。\n"
    "\n"
    "中古トレーラーハウス専門の流通サイト\n"
    "「TRAILER HOUSE SECOND HAND」を\n"
    "運営しているYADOKARI株式会社と申します。\n"
    "出品情報を拝見し、掲載のご提案でご連絡しました！"
)


DM_FOOTER = (
    "▶ TRAILER HOUSE SECOND HAND掲載情報提出フォーム\n"
    "https://info.yadokari.net/form/usedtrailer_sale_information\n"
    "\n"
    "▶ 中古トレーラーハウス専門流通サイト「TRAILER HOUSE SECOND HAND」\n"
    "https://yadokari.net/2nd/\n"
    "\n"
    "▶ YADOKARI株式会社について\n"
    "https://yadokari.company/"
)


def sandwich(middle_body: str) -> str:
    """中段本文をヘッダー・フッターで挟んで完成 DM 本文を返す。"""
    return f"{DM_HEADER}\n\n{middle_body.strip()}\n\n{DM_FOOTER}"


class DmGenerator:
    def __init__(self, api_key: str, model: str, inquiry_url: str) -> None:
        self.client = Anthropic(api_key=api_key)
        self.model = model
        # inquiry_url は現プロンプトでは使わないが、後方互換のため引数は残す
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
            estimated_market_price_yen=classification.estimated_market_price_yen
            if classification.estimated_market_price_yen is not None
            else "不明",
            sales_pitch_hook=classification.sales_pitch_hook or "",
            days_since_posted=listing.days_since_posted(today)
            if listing.posted_date
            else "不明",
            seller_type=classification.seller_type,
            inquiry_url=self.inquiry_url,
        )

        logger.info(
            "generating DM for listing=%s priority=%s",
            listing.article_id,
            classification.priority,
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        data = extract_json(text)

        middle = str(data.get("body") or "").strip()
        if not middle:
            raise ValueError("DM generator returned empty body")

        full_body = sandwich(middle)
        return DmDraft(
            variant_polite=full_body,
            variant_casual="",  # 廃止。後方互換のため空文字
            model_version=self.model,
        )
