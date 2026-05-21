"""GitHub Actions の `${{ vars.X }}` が未定義→空文字で渡ってきても落ちないこと。"""

from __future__ import annotations

import pytest

from watcher.config import load_config


_REQUIRED = {
    "ANTHROPIC_API_KEY": "sk-test",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_KEY": "service-key",
}

_OPTIONAL_EMPTY_KEYS = (
    "WATCHER_CLASSIFIER_MODEL",
    "WATCHER_DM_MODEL",
    "WATCHER_SEARCH_KEYWORDS",
    "WATCHER_MAX_DETAILS_PER_RUN",
    "WATCHER_REQUEST_DELAY_SECONDS",
    "WATCHER_HTTP_TIMEOUT",
    "WATCHER_DRY_RUN",
    "WATCHER_USER_AGENT",
    "YADOKARI_INQUIRY_URL",
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL_ID",
)


def test_load_config_treats_empty_env_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _REQUIRED.items():
        monkeypatch.setenv(k, v)
    for k in _OPTIONAL_EMPTY_KEYS:
        # GitHub Actions の vars が未定義のケースを再現
        monkeypatch.setenv(k, "")

    cfg = load_config()

    assert cfg.request_delay_seconds == pytest.approx(2.5)
    assert cfg.max_details_per_run == 30
    assert cfg.http_timeout_seconds == pytest.approx(20.0)
    assert cfg.classifier_model == "claude-sonnet-4-6"
    assert cfg.dm_model == "claude-sonnet-4-6"
    assert cfg.search_keywords == ("トレーラーハウス",)
    assert cfg.dry_run is False
    assert "Mozilla" in cfg.user_agent
    assert cfg.yadokari_inquiry_url.startswith("https://")
    assert cfg.slack_bot_token is None
    assert cfg.slack_channel_id is None


def test_load_config_required_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        load_config()


def test_load_config_required_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in _REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SUPABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        load_config()
