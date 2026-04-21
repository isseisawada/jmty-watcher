"""Supabaseクライアントの薄いラッパ。

PoCなのでORMは使わず、テーブルに対するCRUDだけ素直に書く。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

from .models import Classification, DmDraft, Listing

logger = logging.getLogger(__name__)


class Db:
    def __init__(self, url: str, key: str) -> None:
        self.client: Client = create_client(url, key)

    # ---------------------------------------------------------------- listings
    def get_listing_id_by_article(self, article_id: str) -> str | None:
        resp = (
            self.client.table("jmty_listings")
            .select("id")
            .eq("article_id", article_id)
            .limit(1)
            .execute()
        )
        if resp.data:
            return resp.data[0]["id"]
        return None

    def upsert_listing(self, listing: Listing) -> str:
        """Upsert by article_id, return listing UUID."""
        row = listing.to_db_row()
        row["last_checked_at"] = datetime.now(timezone.utc).isoformat()
        # Don't overwrite first_seen_at if the row already exists.
        row.pop("first_seen_at", None)
        resp = (
            self.client.table("jmty_listings")
            .upsert(row, on_conflict="article_id")
            .execute()
        )
        if not resp.data:
            raise RuntimeError(f"upsert_listing returned no data for {listing.article_id}")
        return resp.data[0]["id"]

    def list_existing_article_ids(self) -> set[str]:
        resp = self.client.table("jmty_listings").select("article_id").execute()
        return {row["article_id"] for row in (resp.data or [])}

    # --------------------------------------------------------- classifications
    def insert_classification(self, listing_id: str, c: Classification) -> str:
        row: dict[str, Any] = {
            "listing_id": listing_id,
            "is_actual_trailer_house": c.is_actual_trailer_house,
            "seller_type": c.seller_type,
            "trailer_category": c.trailer_category,
            "estimated_market_price_yen": c.estimated_market_price_yen,
            "price_gap_ratio": c.price_gap_ratio,
            "condition_grade": c.condition_grade,
            "priority": c.priority,
            "concerns": c.concerns,
            "sales_pitch_hook": c.sales_pitch_hook,
            "raw_response": c.raw_response,
            "model_version": c.model_version,
        }
        resp = self.client.table("classifications").insert(row).execute()
        return resp.data[0]["id"]

    def latest_classification_priority(self, listing_id: str) -> str | None:
        resp = (
            self.client.table("classifications")
            .select("priority")
            .eq("listing_id", listing_id)
            .order("classified_at", desc=True)
            .limit(1)
            .execute()
        )
        if resp.data:
            return resp.data[0]["priority"]
        return None

    # ------------------------------------------------------------- dm_drafts
    def upsert_dm_draft(self, listing_id: str, draft: DmDraft) -> None:
        row = {
            "listing_id": listing_id,
            "variant_polite": draft.variant_polite,
            "variant_casual": draft.variant_casual,
            "model_version": draft.model_version,
        }
        self.client.table("dm_drafts").upsert(row, on_conflict="listing_id").execute()

    def get_dm_draft(self, listing_id: str) -> DmDraft | None:
        resp = (
            self.client.table("dm_drafts")
            .select("*")
            .eq("listing_id", listing_id)
            .limit(1)
            .execute()
        )
        if not resp.data:
            return None
        r = resp.data[0]
        return DmDraft(
            variant_polite=r.get("variant_polite") or "",
            variant_casual=r.get("variant_casual") or "",
            model_version=r.get("model_version") or "",
        )

    # ----------------------------------------------------------- outreach_log
    def log_outreach_pending(
        self,
        listing_id: str,
        slack_channel_id: str | None,
        slack_message_ts: str | None,
    ) -> str:
        row = {
            "listing_id": listing_id,
            "slack_channel_id": slack_channel_id,
            "slack_message_ts": slack_message_ts,
            "decision": "pending",
        }
        resp = self.client.table("outreach_log").insert(row).execute()
        return resp.data[0]["id"]

    def update_outreach_decision(
        self,
        *,
        listing_id: str,
        decision: str,
        decided_by: str | None,
        final_dm_text: str | None,
    ) -> None:
        row = {
            "decision": decision,
            "decided_by": decided_by,
            "final_dm_text": final_dm_text,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
        self.client.table("outreach_log").update(row).eq(
            "listing_id", listing_id
        ).order("created_at", desc=True).limit(1).execute()
