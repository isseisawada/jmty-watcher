"""Watcher本体のエントリポイント。

実行フロー:
  1. robots.txt を軽くチェック
  2. 各キーワードで一覧ページをfetch（PoCは1ページ目のみ）
  3. 新規 article_id のみ詳細ページをfetch（既出はスキップ）
  4. 全件 Claude Sonnet で分類
  5. priority ∈ {S, A, B} なら DM文を生成
  6. priority ∈ {S, A, B} なら Slack に通知
  7. Supabase に全て保存
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date

from .classifier import Classifier
from .config import Config, load_config
from .db import Db
from .dm_generator import DmGenerator
from .models import Listing
from .scraper import JmtyScraper
from .slack_notifier import SlackNotifier

logger = logging.getLogger("watcher")


NOTIFY_PRIORITIES = {"S", "A", "B"}
DM_PRIORITIES = {"S", "A", "B"}


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def run(cfg: Config) -> int:
    today = date.today()
    db = Db(cfg.supabase_url, cfg.supabase_key)

    classifier = Classifier(cfg.anthropic_api_key, cfg.classifier_model)
    dm_generator = DmGenerator(cfg.anthropic_api_key, cfg.dm_model, cfg.yadokari_inquiry_url)
    notifier: SlackNotifier | None = None
    if cfg.slack_bot_token and cfg.slack_channel_id and not cfg.dry_run:
        notifier = SlackNotifier(cfg.slack_bot_token, cfg.slack_channel_id)

    existing_ids = db.list_existing_article_ids()
    logger.info("existing listings in DB: %d", len(existing_ids))

    with JmtyScraper(
        user_agent=cfg.user_agent,
        request_delay_seconds=cfg.request_delay_seconds,
        timeout=cfg.http_timeout_seconds,
    ) as scraper:
        if not scraper.check_robots_allowed():
            logger.error("robots.txt disallows scraping — aborting run")
            return 1

        all_listings: list[Listing] = []
        for kw in cfg.search_keywords:
            try:
                found = scraper.fetch_listing_page(kw)
                all_listings.extend(found)
            except Exception as e:
                logger.exception("listing page failed for keyword=%s: %s", kw, e)
            time.sleep(cfg.request_delay_seconds)

        # dedupe across keywords
        by_article: dict[str, Listing] = {}
        for listing in all_listings:
            by_article.setdefault(listing.article_id, listing)

        new_listings = [l for l in by_article.values() if l.article_id not in existing_ids]
        logger.info(
            "found %d listings (%d new)", len(by_article), len(new_listings)
        )

        # PoC: 詳細ページは新規のみ、ただし上限で切る
        to_detail = new_listings[: cfg.max_details_per_run]

        for listing in to_detail:
            try:
                scraper.fetch_detail(listing)
            except Exception as e:
                logger.exception("detail fetch failed for %s: %s", listing.article_id, e)

        # ---------------------------------------------------------------- pipeline
        for listing in to_detail:
            try:
                process_listing(
                    listing=listing,
                    db=db,
                    classifier=classifier,
                    dm_generator=dm_generator,
                    notifier=notifier,
                    today=today,
                    dry_run=cfg.dry_run,
                )
            except Exception as e:
                logger.exception("pipeline failed for %s: %s", listing.article_id, e)

    logger.info("done")
    return 0


def process_listing(
    *,
    listing: Listing,
    db: Db,
    classifier: Classifier,
    dm_generator: DmGenerator,
    notifier: SlackNotifier | None,
    today: date,
    dry_run: bool,
) -> None:
    listing_id = db.upsert_listing(listing)
    logger.info("upserted listing_id=%s article=%s", listing_id, listing.article_id)

    classification = classifier.classify(listing, today=today)
    db.insert_classification(listing_id, classification)
    logger.info(
        "classified article=%s priority=%s trailer=%s",
        listing.article_id,
        classification.priority,
        classification.is_actual_trailer_house,
    )

    if classification.priority in DM_PRIORITIES and classification.is_actual_trailer_house:
        try:
            draft = dm_generator.generate(listing, classification, today=today)
            db.upsert_dm_draft(listing_id, draft)
        except Exception as e:
            logger.exception("DM generation failed for %s: %s", listing.article_id, e)

    if classification.priority in NOTIFY_PRIORITIES:
        if dry_run or notifier is None:
            logger.info("[dry-run] would notify Slack for %s", listing.article_id)
            return
        ts = notifier.post_listing(
            listing_id=listing_id,
            listing=listing,
            classification=classification,
            days_since_posted=listing.days_since_posted(today),
        )
        if ts:
            db.log_outreach_pending(
                listing_id=listing_id,
                slack_channel_id=notifier.channel_id,
                slack_message_ts=ts,
            )


def main() -> int:
    configure_logging()
    cfg = load_config()
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
