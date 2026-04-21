"""Slack Interactive Components 用 Vercel Serverless ハンドラ。

エンドポイント: POST /api/slack/interactive
- [✉️ DM文を見る] → モーダルを views.open で開く
- [🙅 スルー] → Supabase に decision='rejected' を記録、メッセージを更新
- モーダル内「丁寧版を採用」「フランク版を採用」→ decision='approved' を記録

Slack 署名検証は `SLACK_SIGNING_SECRET` を使って自前で実装する。
BaseHTTPRequestHandler ベースで Vercel Python Runtime で動く形にしている。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any

from slack_sdk import WebClient
from supabase import create_client

logger = logging.getLogger("slack_interactive")
logging.basicConfig(level=logging.INFO)


SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")

_slack = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None
_supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None


def _verify_slack_signature(headers: dict[str, str], raw_body: bytes) -> bool:
    if not SLACK_SIGNING_SECRET:
        logger.error("SLACK_SIGNING_SECRET is not set")
        return False
    ts = headers.get("x-slack-request-timestamp") or headers.get("X-Slack-Request-Timestamp")
    sig = headers.get("x-slack-signature") or headers.get("X-Slack-Signature")
    if not ts or not sig:
        return False
    try:
        if abs(time.time() - int(ts)) > 60 * 5:
            return False
    except ValueError:
        return False
    base = b"v0:" + ts.encode("utf-8") + b":" + raw_body
    digest = hmac.new(
        SLACK_SIGNING_SECRET.encode("utf-8"), base, hashlib.sha256
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, sig)


def _log_outreach(
    listing_id: str,
    *,
    decision: str,
    decided_by: str | None,
    final_dm_text: str | None,
) -> None:
    if _supabase is None:
        logger.warning("supabase not configured; skipping outreach log")
        return
    row = {
        "decision": decision,
        "decided_by": decided_by,
        "final_dm_text": final_dm_text,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        existing = (
            _supabase.table("outreach_log")
            .select("id")
            .eq("listing_id", listing_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if existing.data:
            _supabase.table("outreach_log").update(row).eq(
                "id", existing.data[0]["id"]
            ).execute()
        else:
            _supabase.table("outreach_log").insert(
                {"listing_id": listing_id, **row}
            ).execute()
    except Exception as e:
        logger.exception("outreach log update failed: %s", e)


def _fetch_dm_draft(listing_id: str) -> dict[str, Any] | None:
    if _supabase is None:
        return None
    resp = (
        _supabase.table("dm_drafts")
        .select("variant_polite,variant_casual")
        .eq("listing_id", listing_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _fetch_listing(listing_id: str) -> dict[str, Any] | None:
    if _supabase is None:
        return None
    resp = (
        _supabase.table("jmty_listings")
        .select("article_id,title,url")
        .eq("id", listing_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _build_dm_modal(listing_id: str, draft: dict[str, Any], listing: dict[str, Any]) -> dict[str, Any]:
    title = (listing.get("title") or "DM文案")[:40]
    polite = (draft.get("variant_polite") or "(生成されていません)").strip()
    casual = (draft.get("variant_casual") or "(生成されていません)").strip()

    return {
        "type": "modal",
        "callback_id": "dm_modal",
        "private_metadata": listing_id,
        "title": {"type": "plain_text", "text": "DM文案", "emoji": True},
        "close": {"type": "plain_text", "text": "閉じる"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*対象出品*: <{listing.get('url', '')}|{title}>",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*丁寧版*\n```{polite}```"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "approve_polite",
                        "text": {"type": "plain_text", "text": "丁寧版を採用してコピー"},
                        "style": "primary",
                        "value": listing_id,
                    }
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*フランク版*\n```{casual}```"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "approve_casual",
                        "text": {"type": "plain_text", "text": "フランク版を採用してコピー"},
                        "style": "primary",
                        "value": listing_id,
                    }
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "「採用」を押したら、本文をコピーしてジモティのメッセージ欄に"
                            "貼り付けてください。送信は手動です。"
                        ),
                    }
                ],
            },
        ],
    }


def _handle_block_action(payload: dict[str, Any]) -> tuple[int, dict[str, Any] | str]:
    actions = payload.get("actions") or []
    if not actions:
        return 200, ""
    action = actions[0]
    action_id = action.get("action_id", "")
    listing_id = action.get("value") or ""
    user = (payload.get("user") or {}).get("id")

    if action_id == "view_dm":
        trigger_id = payload.get("trigger_id")
        draft = _fetch_dm_draft(listing_id) or {}
        listing = _fetch_listing(listing_id) or {}
        modal = _build_dm_modal(listing_id, draft, listing)
        if _slack and trigger_id:
            try:
                _slack.views_open(trigger_id=trigger_id, view=modal)
            except Exception as e:
                logger.exception("views_open failed: %s", e)
        return 200, ""

    if action_id == "reject":
        _log_outreach(
            listing_id, decision="rejected", decided_by=user, final_dm_text=None
        )
        _update_original_as_resolved(payload, "🙅 スルー済み")
        return 200, ""

    if action_id in ("approve_polite", "approve_casual"):
        draft = _fetch_dm_draft(listing_id) or {}
        body = draft.get("variant_polite" if action_id == "approve_polite" else "variant_casual")
        _log_outreach(
            listing_id, decision="approved", decided_by=user, final_dm_text=body
        )
        # モーダル内アクションは response を返す必要なし
        return 200, ""

    if action_id == "open_listing":
        # URLボタン、サーバー側処理なし
        return 200, ""

    logger.info("unhandled action_id=%s", action_id)
    return 200, ""


def _update_original_as_resolved(payload: dict[str, Any], note: str) -> None:
    """元メッセージの先頭ブロックに取り消し線風の注記を足す。"""
    msg = payload.get("message") or {}
    channel = (payload.get("channel") or {}).get("id")
    ts = msg.get("ts")
    blocks = msg.get("blocks") or []
    if not channel or not ts or not blocks or _slack is None:
        return
    try:
        new_blocks: list[dict[str, Any]] = [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*{note}*"}],
            },
            *blocks,
        ]
        _slack.chat_update(
            channel=channel,
            ts=ts,
            text=note,
            blocks=new_blocks,
        )
    except Exception as e:
        logger.warning("chat_update failed: %s", e)


# ---------------------------------------------------------------------------
# Vercel Python runtime entrypoint
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):  # noqa: N801 (required name by Vercel)
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or "0")
        raw_body = self.rfile.read(length)
        headers_lc = {k.lower(): v for k, v in self.headers.items()}

        if not _verify_slack_signature(headers_lc, raw_body):
            self._reply(401, "invalid signature")
            return

        # Slackは application/x-www-form-urlencoded で payload=... を送る
        parsed = urllib.parse.parse_qs(raw_body.decode("utf-8"))
        payload_raw = (parsed.get("payload") or [""])[0]
        if not payload_raw:
            self._reply(400, "missing payload")
            return

        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            self._reply(400, "invalid json")
            return

        ptype = payload.get("type")
        try:
            if ptype == "block_actions":
                status, body = _handle_block_action(payload)
            elif ptype == "view_submission":
                status, body = 200, {"response_action": "clear"}
            else:
                logger.info("unhandled payload type=%s", ptype)
                status, body = 200, ""
        except Exception as e:
            logger.exception("handler error: %s", e)
            status, body = 500, "internal error"

        self._reply(status, body)

    def do_GET(self) -> None:  # noqa: N802
        self._reply(200, "slack interactive handler ok")

    def _reply(self, status: int, body: Any) -> None:
        if isinstance(body, dict):
            payload = json.dumps(body).encode("utf-8")
            content_type = "application/json"
        else:
            payload = str(body).encode("utf-8")
            content_type = "text/plain; charset=utf-8"
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
