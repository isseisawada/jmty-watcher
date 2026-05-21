"""SheetsNotifier の payload 構築と通信エラーハンドリング。"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from watcher.models import Classification, Listing
from watcher.sheets_notifier import (
    SheetsNotifier,
    _format_concerns,
    _format_days,
    _format_gap_ratio,
    build_sheet_payload,
)


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
        trailer_category="residential",
        estimated_market_price_yen=2_000_000,
        price_gap_ratio=0.5,
        condition_grade="B",
        priority=priority,
        concerns=["水回り不明", "輸送経路要確認"],
        sales_pitch_hook="築浅で設備完備",
        model_version="claude-sonnet-4-6",
    )


def test_payload_includes_all_expected_fields() -> None:
    payload = build_sheet_payload(
        listing=_listing(),
        classification=_classification(),
        token="t",
        dm_polite="お世話になっております。XX社の△△と申します...",
        days_since_posted=790,
        added_at="2026-05-21 17:30",
    )
    assert payload == {
        "token": "t",
        "added_at": "2026-05-21 17:30",
        "article_id": "article-xyz",
        "priority": "B",
        "title": "トレーラーハウス売ります",
        "location": "千葉 柏市",
        "days_since_posted": "790日",
        "price_yen": 1_500_000,
        "estimated_market_price_yen": 2_000_000,
        "price_gap_ratio": "+50%",
        "condition_grade": "B",
        "sales_pitch_hook": "築浅で設備完備",
        "concerns": "・水回り不明\n・輸送経路要確認",
        "url": "https://jmty.jp/x/sale/article-xyz",
        "thumbnail_url": "https://img.cdn.jmty.jp/x.jpg",
        "dm_polite": "お世話になっております。XX社の△△と申します...",
    }


def test_payload_handles_missing_classification_fields() -> None:
    cls = _classification()
    cls.price_gap_ratio = None
    cls.condition_grade = ""
    cls.concerns = []
    cls.sales_pitch_hook = ""
    payload = build_sheet_payload(
        listing=_listing(),
        classification=cls,
        token=None,
        days_since_posted=None,
    )
    assert payload["days_since_posted"] == ""
    assert payload["price_gap_ratio"] == ""
    assert payload["condition_grade"] == ""
    assert payload["sales_pitch_hook"] == ""
    assert payload["concerns"] == ""
    assert payload["dm_polite"] == ""


def test_format_gap_ratio_signs() -> None:
    assert _format_gap_ratio(0.5) == "+50%"
    assert _format_gap_ratio(-0.25) == "-25%"
    assert _format_gap_ratio(0) == "+0%"
    assert _format_gap_ratio(None) == ""


def test_format_days() -> None:
    assert _format_days(0) == "0日"
    assert _format_days(790) == "790日"
    assert _format_days(None) == ""


def test_format_concerns_bullets() -> None:
    assert _format_concerns(["a", "b"]) == "・a\n・b"
    assert _format_concerns(["a", "", None]) == "・a"  # falsy items dropped  # type: ignore[list-item]
    assert _format_concerns([]) == ""
    assert _format_concerns(None) == ""


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
