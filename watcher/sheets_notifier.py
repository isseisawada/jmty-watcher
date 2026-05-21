"""Google Sheets への記録を担当するモジュール。

Google Apps Script を「ウェブアプリとしてデプロイ」して得られる URL に POST する。
Service Account や gspread を使わない分、設定が軽い。

POST する JSON 構造:
    {
        "token": "簡易認証トークン",
        "article_id": "...",
        "added_at": "2026-05-21 17:30",
        "priority": "S" | "A" | "B",
        "title": "...",
        "location": "千葉 柏市",
        "price_yen": 1500000,
        "estimated_market_price_yen": 2000000,
        "url": "https://jmty.jp/...",
        "thumbnail_url": "https://img.cdn.jmty.jp/..."
    }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

from .models import Classification, Listing

logger = logging.getLogger(__name__)


_JST = timezone(timedelta(hours=9))


def _format_now_jst() -> str:
    return datetime.now(timezone.utc).astimezone(_JST).strftime("%Y-%m-%d %H:%M")


def _format_location(listing: Listing) -> str:
    parts = [listing.prefecture or "", listing.city or ""]
    return " ".join(p for p in parts if p) or ""


def _format_gap_ratio(ratio: float | None) -> str:
    if ratio is None:
        return ""
    return f"{ratio * 100:+.0f}%"


def _format_days(days: int | None) -> str:
    if days is None:
        return ""
    return f"{days}日"


def _format_concerns(items: list[str] | None) -> str:
    if not items:
        return ""
    return "\n".join(f"・{x}" for x in items if x)


def build_sheet_payload(
    *,
    listing: Listing,
    classification: Classification,
    token: str | None,
    dm_polite: str | None = None,
    days_since_posted: int | None = None,
    added_at: str | None = None,
) -> dict[str, Any]:
    return {
        "token": token or "",
        "added_at": added_at or _format_now_jst(),
        "article_id": listing.article_id,
        "priority": classification.priority,
        "title": listing.title or "",
        "location": _format_location(listing),
        "days_since_posted": _format_days(days_since_posted),
        "price_yen": listing.price_yen,
        "estimated_market_price_yen": classification.estimated_market_price_yen,
        "price_gap_ratio": _format_gap_ratio(classification.price_gap_ratio),
        "condition_grade": classification.condition_grade or "",
        "sales_pitch_hook": classification.sales_pitch_hook or "",
        "concerns": _format_concerns(classification.concerns),
        "url": listing.url,
        "thumbnail_url": listing.thumbnail_url or "",
        "dm_polite": dm_polite or "",
    }


class SheetsNotifier:
    def __init__(
        self,
        webhook_url: str,
        token: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.webhook_url = webhook_url
        self.token = token
        self._client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SheetsNotifier":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def append_listing(
        self,
        *,
        listing: Listing,
        classification: Classification,
        dm_polite: str | None = None,
        days_since_posted: int | None = None,
    ) -> bool:
        """Sheets に1行追加。成功なら True、失敗ログを残して False。"""
        payload = build_sheet_payload(
            listing=listing,
            classification=classification,
            token=self.token,
            dm_polite=dm_polite,
            days_since_posted=days_since_posted,
        )
        try:
            resp = self._client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "Sheets append failed for %s: %s", listing.article_id, e
            )
            return False

        if not data.get("ok"):
            logger.error(
                "Sheets webhook returned error for %s: %s",
                listing.article_id,
                data.get("error"),
            )
            return False

        logger.info(
            "appended to Sheets: article=%s row=%s",
            listing.article_id,
            data.get("row"),
        )
        return True
