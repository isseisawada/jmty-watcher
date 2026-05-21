"""ジモティ現状の全 listing を1回で取り込むワンショット CLI。

通常の cron (`watcher.main`) は 1 ページ目だけしか見ないが、こちらは:
1. 各 keyword の全ページを巡回
2. keyword 間の重複を排除
3. DB に既存の article_id はスキップ
4. 残りに対して通常の `process_listing` パイプライン（詳細 fetch → Claude 分類 →
   DM 生成 → Sheets/Slack 通知 → DB 保存）を一気に流す

ローカル実行前提（GitHub Actions の 15 分タイムアウトでは終わらない）。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date

from .classifier import Classifier
from .config import load_config
from .db import Db
from .dm_generator import DmGenerator
from .main import configure_logging, process_listing
from .models import Listing
from .scraper import JmtyScraper
from .sheets_notifier import SheetsNotifier
from .slack_notifier import SlackNotifier

logger = logging.getLogger("bulk_backfill")


def crawl_all_pages(
    scraper: JmtyScraper,
    keyword: str,
    *,
    max_pages: int,
    delay_seconds: float,
) -> list[Listing]:
    """`count_jmty` と同じ打ち切り条件で全ページ巡回し、出会った Listing を返す。"""
    seen_ids: set[str] = set()
    out: list[Listing] = []
    for page in range(1, max_pages + 1):
        try:
            listings = scraper.fetch_listing_page(keyword, page=page)
        except Exception as e:  # noqa: BLE001
            logger.warning("page %d failed for %s: %s", page, keyword, e)
            break
        if not listings:
            logger.info("page %d returned 0 listings → stop", page)
            break

        new_this_page = 0
        for lst in listings:
            if lst.article_id not in seen_ids:
                seen_ids.add(lst.article_id)
                out.append(lst)
                new_this_page += 1

        logger.info(
            "  page %d: %d items (new=%d, total=%d)",
            page,
            len(listings),
            new_this_page,
            len(seen_ids),
        )
        if new_this_page == 0:
            logger.info("page %d added 0 new article_ids → stop", page)
            break
        if page < max_pages:
            time.sleep(delay_seconds)
    return out


def dedupe_keep_first(listings_by_kw: dict[str, list[Listing]]) -> dict[str, Listing]:
    """keyword 別の listing リストを (article_id -> Listing) に統合（先勝ち）。"""
    out: dict[str, Listing] = {}
    for _, listings in listings_by_kw.items():
        for lst in listings:
            out.setdefault(lst.article_id, lst)
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--keywords",
        default=None,
        help="カンマ区切り。未指定なら WATCHER_SEARCH_KEYWORDS",
    )
    p.add_argument("--max-pages", type=int, default=20, help="keyword あたりの上限")
    p.add_argument(
        "--max-classify",
        type=int,
        default=None,
        help="安全弁: 詳細 fetch + 分類する最大件数（未指定なら全件）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="クロールだけ実行し、新規件数を表示して終了。Claude API は呼ばない",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging()
    cfg = load_config()
    today = date.today()

    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    else:
        keywords = list(cfg.search_keywords)
    if not keywords:
        logger.error("no keywords specified")
        return 1

    logger.info(
        "bulk backfill: keywords=%s max_pages=%d dry_run=%s",
        keywords,
        args.max_pages,
        args.dry_run,
    )

    db = Db(cfg.supabase_url, cfg.supabase_key)
    existing_ids = db.list_existing_article_ids()
    logger.info("existing listings in DB: %d", len(existing_ids))

    listings_by_kw: dict[str, list[Listing]] = {}
    with JmtyScraper(
        user_agent=cfg.user_agent,
        request_delay_seconds=cfg.request_delay_seconds,
        timeout=cfg.http_timeout_seconds,
    ) as scraper:
        if not scraper.check_robots_allowed():
            logger.error("robots.txt disallows scraping")
            return 1

        for kw in keywords:
            logger.info("--- crawling keyword: %s ---", kw)
            try:
                listings_by_kw[kw] = crawl_all_pages(
                    scraper,
                    kw,
                    max_pages=args.max_pages,
                    delay_seconds=cfg.request_delay_seconds,
                )
            except Exception as e:
                logger.exception("crawl failed for %s: %s", kw, e)
                listings_by_kw[kw] = []
            if kw != keywords[-1]:
                time.sleep(cfg.request_delay_seconds)

        by_article = dedupe_keep_first(listings_by_kw)
        new_listings = [
            lst for lst in by_article.values() if lst.article_id not in existing_ids
        ]
        logger.info(
            "crawled unique=%d, new (not in DB)=%d", len(by_article), len(new_listings)
        )
        for kw, lst in listings_by_kw.items():
            logger.info("  - %s: %d (pre-dedupe)", kw, len(lst))

        if args.max_classify is not None:
            new_listings = new_listings[: args.max_classify]
            logger.info("safety: limited to %d listings", len(new_listings))

        if args.dry_run:
            logger.info("[dry-run] would process %d new listings", len(new_listings))
            for lst in new_listings[:30]:
                logger.info(
                    "  - %s: %s", lst.article_id, (lst.title or "")[:60]
                )
            if len(new_listings) > 30:
                logger.info("  ... and %d more", len(new_listings) - 30)
            return 0

        if not new_listings:
            logger.info("nothing to do")
            return 0

        logger.info("fetching details for %d listings ...", len(new_listings))
        for i, lst in enumerate(new_listings, 1):
            try:
                scraper.fetch_detail(lst)
            except Exception as e:
                logger.exception("detail fetch failed for %s: %s", lst.article_id, e)
            if i % 10 == 0 or i == len(new_listings):
                logger.info("  detail fetch progress: %d/%d", i, len(new_listings))

        classifier = Classifier(cfg.anthropic_api_key, cfg.classifier_model)
        dm_generator = DmGenerator(
            cfg.anthropic_api_key, cfg.dm_model, cfg.yadokari_inquiry_url
        )
        notifier: SlackNotifier | None = None
        if cfg.slack_bot_token and cfg.slack_channel_id:
            notifier = SlackNotifier(
                cfg.slack_bot_token,
                cfg.slack_channel_id,
                sheets_view_url=cfg.sheets_view_url,
            )
        sheets: SheetsNotifier | None = None
        if cfg.sheets_webhook_url:
            sheets = SheetsNotifier(cfg.sheets_webhook_url, cfg.sheets_webhook_token)

        try:
            for i, lst in enumerate(new_listings, 1):
                try:
                    process_listing(
                        listing=lst,
                        db=db,
                        classifier=classifier,
                        dm_generator=dm_generator,
                        notifier=notifier,
                        sheets=sheets,
                        today=today,
                        dry_run=False,
                    )
                except Exception as e:
                    logger.exception(
                        "pipeline failed for %s: %s", lst.article_id, e
                    )
                if i % 10 == 0 or i == len(new_listings):
                    logger.info("  pipeline progress: %d/%d", i, len(new_listings))
        finally:
            if sheets is not None:
                sheets.close()

    logger.info("done: processed %d listings", len(new_listings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
