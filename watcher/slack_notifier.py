"""Slack通知。

Block Kit を組み立てて `chat.postMessage` で投下する。
「DM文を見る」の実体はVercelハンドラ側のモーダル。
ここではペイロードに listing_id を value として載せるだけ。
"""

from __future__ import annotations

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .models import Classification, Listing

logger = logging.getLogger(__name__)

PRIORITY_EMOJI = {"S": "🔥", "A": "⭐", "B": "🔸", "C": "▫️"}


class SlackNotifier:
    def __init__(self, bot_token: str, channel_id: str) -> None:
        self.client = WebClient(token=bot_token)
        self.channel_id = channel_id

    def post_listing(
        self,
        listing_id: str,
        listing: Listing,
        classification: Classification,
        days_since_posted: int | None,
    ) -> str | None:
        """通知を投稿し、Slack の message ts を返す。失敗時は None。"""
        blocks = build_listing_blocks(
            listing_id=listing_id,
            listing=listing,
            classification=classification,
            days_since_posted=days_since_posted,
        )
        priority = classification.priority
        text_fallback = f"[{priority}] {listing.title or 'ジモティ新着案件'}"
        try:
            resp = self.client.chat_postMessage(
                channel=self.channel_id,
                text=text_fallback,
                blocks=blocks,
                unfurl_links=False,
                unfurl_media=False,
            )
            return resp.get("ts")
        except SlackApiError as e:
            logger.error("Slack postMessage failed: %s", e.response.data if e.response else e)
            return None


def build_listing_blocks(
    *,
    listing_id: str,
    listing: Listing,
    classification: Classification,
    days_since_posted: int | None,
) -> list[dict[str, Any]]:
    priority = classification.priority
    emoji = PRIORITY_EMOJI.get(priority, "")
    title_text = (listing.title or "(タイトルなし)")[:60]
    header_text = f"{emoji} [{priority}] {title_text}"[:150]

    price_text = f"{listing.price_yen:,}円" if listing.price_yen is not None else "価格不明"
    market_text = (
        f"{classification.estimated_market_price_yen:,}円"
        if classification.estimated_market_price_yen
        else "不明"
    )
    gap = classification.price_gap_ratio
    gap_text = f"{gap * 100:+.0f}%" if gap is not None else "—"
    location = f"{listing.prefecture or ''} {listing.city or ''}".strip() or "不明"
    days_text = f"{days_since_posted}日" if days_since_posted is not None else "不明"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*価格*\n{price_text}"},
                {"type": "mrkdwn", "text": f"*推定市場価格*\n{market_text}"},
                {"type": "mrkdwn", "text": f"*乖離率*\n{gap_text}"},
                {"type": "mrkdwn", "text": f"*所在地*\n{location}"},
                {"type": "mrkdwn", "text": f"*経過日数*\n{days_text}"},
                {"type": "mrkdwn", "text": f"*状態*\n{classification.condition_grade}"},
            ],
        },
    ]

    if listing.thumbnail_url:
        blocks.append(
            {
                "type": "image",
                "image_url": listing.thumbnail_url,
                "alt_text": title_text,
            }
        )

    if classification.sales_pitch_hook:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*引きポイント*\n{classification.sales_pitch_hook}",
                },
            }
        )

    if classification.concerns:
        bullets = "\n".join(f"• {c}" for c in classification.concerns[:5])
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*懸念点*\n{bullets}"},
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"出品者: {classification.seller_type} / "
                        f"種別: {classification.trailer_category} / "
                        f"article_id: `{listing.article_id}`"
                    ),
                }
            ],
        }
    )

    actions: list[dict[str, Any]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "✉️ DM文を見る", "emoji": True},
            "style": "primary",
            "action_id": "view_dm",
            "value": listing_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "🔗 出品ページ", "emoji": True},
            "action_id": "open_listing",
            "url": listing.url,
            "value": listing_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "🙅 スルー", "emoji": True},
            "style": "danger",
            "action_id": "reject",
            "value": listing_id,
        },
    ]
    blocks.extend([{"type": "divider"}, {"type": "actions", "elements": actions}])

    return blocks
