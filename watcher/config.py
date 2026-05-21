"""Runtime configuration loaded from env vars (GitHub Actions secrets or .env)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _get(name: str, default: str | None = None, required: bool = False) -> str | None:
    raw = os.environ.get(name)
    # GitHub Actions の `${{ vars.X }}` は未定義時に空文字を流し込んでくるため、
    # 空文字も「未設定」として default にフォールバックする。
    value = raw if raw not in (None, "") else default
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    classifier_model: str
    dm_model: str

    supabase_url: str
    supabase_key: str

    slack_bot_token: str | None
    slack_channel_id: str | None

    sheets_webhook_url: str | None
    sheets_webhook_token: str | None

    search_keywords: tuple[str, ...]
    max_details_per_run: int
    request_delay_seconds: float
    dry_run: bool
    http_timeout_seconds: float
    user_agent: str

    yadokari_inquiry_url: str


def load_config() -> Config:
    keywords_raw = _get("WATCHER_SEARCH_KEYWORDS", "トレーラーハウス") or "トレーラーハウス"
    keywords = tuple(k.strip() for k in keywords_raw.split(",") if k.strip())

    return Config(
        anthropic_api_key=_get("ANTHROPIC_API_KEY", required=True),
        classifier_model=_get("WATCHER_CLASSIFIER_MODEL", "claude-sonnet-4-6"),
        dm_model=_get("WATCHER_DM_MODEL", "claude-sonnet-4-6"),
        supabase_url=_get("SUPABASE_URL", required=True),
        supabase_key=_get("SUPABASE_SERVICE_KEY") or _get("SUPABASE_KEY", required=True),
        slack_bot_token=_get("SLACK_BOT_TOKEN"),
        slack_channel_id=_get("SLACK_CHANNEL_ID"),
        sheets_webhook_url=_get("SHEETS_WEBHOOK_URL"),
        sheets_webhook_token=_get("SHEETS_WEBHOOK_TOKEN"),
        search_keywords=keywords,
        max_details_per_run=int(_get("WATCHER_MAX_DETAILS_PER_RUN", "30")),
        request_delay_seconds=float(_get("WATCHER_REQUEST_DELAY_SECONDS", "2.5")),
        dry_run=(_get("WATCHER_DRY_RUN", "false") or "").lower() == "true",
        http_timeout_seconds=float(_get("WATCHER_HTTP_TIMEOUT", "20")),
        user_agent=_get(
            "WATCHER_USER_AGENT",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36",
        ),
        yadokari_inquiry_url=_get(
            "YADOKARI_INQUIRY_URL",
            "https://info.yadokari.net/form/usedtrailer_sale",
        ),
    )
