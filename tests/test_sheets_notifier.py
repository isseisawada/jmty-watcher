"""SheetsNotifier の payload 構築と通信エラーハンドリング。"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from watcher.models import Classification, Listing
from watcher.sheets_notifier import SheetsNotifier, build_sheet_payload


def _listing() -> Listing:
    return Listing(
        article_id="article-xyz",
        url="https://jmty.jp/x/sale/article-xyz",
        title="トレーラーハウス売ります",
        price_yen=1_500_000,
        prefecture="千葉",
        city="柏市",
        category_label="その他",
        thumbnail_url="https://img.cdn.jmty.jp/x.jpg",
        posted_date=date(2026, 5, 19),
    )


def _classification(priority: str = "B") -> Classification:
    return Classification(
        is_actual_trailer_house=True,
        seller_type="individual",
        trailer_category="trailer_house",
        estimated_market_price_yen=2_000_000,
        price_gap_ratio=-0.25,
        condition_grade="good",
        priority=priority,
        concerns=[],
        sales_pitch_hook="安い",
        model_version="claude-sonnet-4-6",
    )


def test_payload_includes_all_expected_fields() -> None:
    payload = build_sheet_payload(
        listing=_listing(),
        classification=_classification(),
        token="t",
        dm_polite="お世話になっております。XX社の△△と申します...",
        added_at="2026-05-21 17:30",
    )
    assert payload == {
        "token": "t",
        "added_at": "2026-05-21 17:30",
        "article_id": "article-xyz",
        "priority": "B",
        "title": "トレーラーハウス売ります",
        "location": "千葉 柏市",
        "price_yen": 1_500_000,
        "estimated_market_price_yen": 2_000_000,
        "url": "https://jmty.jp/x/sale/article-xyz",
        "thumbnail_url": "https://img.cdn.jmty.jp/x.jpg",
        "dm_polite": "お世話になっております。XX社の△△と申します...",
    }


def test_payload_without_dm_polite_emits_empty_string() -> None:
    payload = build_sheet_payload(
        listing=_listing(), classification=_classification(), token=None
    )
    assert payload["dm_polite"] == ""


def test_payload_missing_location_parts_join_cleanly() -> None:
    listing = _listing()
    listing.prefecture = None
    listing.city = None
    payload = build_sheet_payload(
        listing=listing, classification=_classification(), token=None
    )
    assert payload["location"] == ""
    assert payload["token"] == ""


def _make_notifier(handler) -> SheetsNotifier:
    transport = httpx.MockTransport(handler)
    n = SheetsNotifier("https://example.invalid/exec", token="t")
    n._client.close()
    n._client = httpx.Client(transport=transport)
    return n


def test_append_listing_succeeds_on_ok_response() -> None:
    captured: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["json"] = req.read()
        return httpx.Response(200, json={"ok": True, "row": 42})

    n = _make_notifier(handler)
    try:
        ok = n.append_listing(listing=_listing(), classification=_classification())
    finally:
        n.close()
    assert ok is True
    assert b'"article-xyz"' in captured["json"]


def test_append_listing_returns_false_on_error_payload() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "unauthorized"})

    n = _make_notifier(handler)
    try:
        ok = n.append_listing(listing=_listing(), classification=_classification())
    finally:
        n.close()
    assert ok is False


def test_append_listing_returns_false_on_http_5xx() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    n = _make_notifier(handler)
    try:
        ok = n.append_listing(listing=_listing(), classification=_classification())
    finally:
        n.close()
    assert ok is False


def test_append_listing_returns_false_on_network_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    n = _make_notifier(handler)
    try:
        ok = n.append_listing(listing=_listing(), classification=_classification())
    finally:
        n.close()
    assert ok is False


def test_sheets_webhook_config_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """env が無くても load_config は通る、watcher は sheets を None で動く想定。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "s")
    monkeypatch.delenv("SHEETS_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SHEETS_WEBHOOK_TOKEN", raising=False)
    from watcher.config import load_config

    cfg = load_config()
    assert cfg.sheets_webhook_url is None
    assert cfg.sheets_webhook_token is None
