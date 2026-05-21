"""ジモティの listing 数を計測する。

軽量モード（デフォルト）:
    一覧ページだけ叩いて article_id を集める。詳細ページは fetch しない。

詳細プローブモード（--probe-details）:
    全ユニーク article_id の詳細ページも fetch して
    「お問い合わせの受付は終了いたしました」マーカーを集計。
    Claude API は呼ばない（コストは HTTP 取得分のみ）。

使い方:
    uv run python -m watcher.count_jmty
    uv run python -m watcher.count_jmty --keywords トレーラーハウス,モバイルハウス
    uv run python -m watcher.count_jmty --probe-details
    uv run python -m watcher.count_jmty --probe-details --max-pages 30

打ち切り:
- 一覧が 0 件
- 新規 article_id が増えなかったページに到達 (jmty の先頭ループバック対策)
- --max-pages の固い上限

403/timeout が出る環境（GitHub Runner 等）では動かない。ローカル Mac から実行する。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .config import load_config
from .main import configure_logging
from .models import Listing
from .scraper import JmtyScraper

logger = logging.getLogger("count_jmty")


DEFAULT_KEYWORDS = ["トレーラーハウス"]


def count_keyword(
    scraper: JmtyScraper,
    keyword: str,
    *,
    max_pages: int,
    delay_seconds: float,
) -> tuple[list[Listing], int]:
    """全ページ巡回。出会った Listing のリスト（重複は1件のみ）と最終ページ番号を返す。"""
    seen_ids: set[str] = set()
    out: list[Listing] = []
    page = 0
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
            "  page %d: %d items (unique +%d, total=%d)",
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

    return out, page


def probe_closed(
    scraper: JmtyScraper,
    listings: list[Listing],
    *,
    delay_seconds: float,
) -> tuple[int, int, list[str]]:
    """各 listing の詳細を fetch して closed の数を返す。

    Claude API は呼ばない。閉じている article_id のリストも返す（あとでログ確認可能）。
    """
    open_count = 0
    closed_count = 0
    closed_ids: list[str] = []
    total = len(listings)
    for i, lst in enumerate(listings, 1):
        try:
            scraper.fetch_detail(lst)
        except Exception as e:  # noqa: BLE001
            logger.warning("detail fetch failed for %s: %s", lst.article_id, e)
            continue
        if lst.inquiry_closed:
            closed_count += 1
            closed_ids.append(lst.article_id)
        else:
            open_count += 1
        if i % 10 == 0 or i == total:
            logger.info(
                "  detail probe progress: %d/%d (open=%d, closed=%d)",
                i,
                total,
                open_count,
                closed_count,
            )
        if i < total:
            time.sleep(delay_seconds)
    return open_count, closed_count, closed_ids


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--keywords",
        default=None,
        help="カンマ区切り。未指定なら WATCHER_SEARCH_KEYWORDS or 'トレーラーハウス'",
    )
    p.add_argument("--max-pages", type=int, default=30)
    p.add_argument("--delay", type=float, default=None, help="リクエスト間 sleep 秒")
    p.add_argument(
        "--probe-details",
        action="store_true",
        help="全ユニーク listing の詳細を fetch して inquiry_closed を集計する",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging()
    cfg = load_config()

    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    else:
        keywords = list(cfg.search_keywords) or DEFAULT_KEYWORDS

    delay = args.delay if args.delay is not None else cfg.request_delay_seconds

    logger.info(
        "counting jmty listings: keywords=%s max_pages=%d delay=%.1fs probe_details=%s",
        keywords,
        args.max_pages,
        delay,
        args.probe_details,
    )

    per_keyword: dict[str, list[Listing]] = {}
    unique: dict[str, Listing] = {}

    with JmtyScraper(
        user_agent=cfg.user_agent,
        request_delay_seconds=delay,
        timeout=cfg.http_timeout_seconds,
    ) as scraper:
        if not scraper.check_robots_allowed():
            logger.error("robots.txt disallows scraping — aborting")
            return 1

        for kw in keywords:
            logger.info("--- keyword: %s ---", kw)
            listings, pages = count_keyword(
                scraper, kw, max_pages=args.max_pages, delay_seconds=delay
            )
            per_keyword[kw] = listings
            for lst in listings:
                unique.setdefault(lst.article_id, lst)
            logger.info(
                "keyword=%s: %d listings in %d page(s)", kw, len(listings), pages
            )
            if kw != keywords[-1]:
                time.sleep(delay)

        print("\n===== Listing count (一覧ページのみ) =====")
        total_per_kw = 0
        for kw, lst in per_keyword.items():
            print(f"  {kw}: {len(lst)}")
            total_per_kw += len(lst)
        print("  ------")
        print(f"  合計 (keyword 間の重複あり): {total_per_kw}")
        print(f"  ユニーク (article_id でdedup): {len(unique)}")

        if not args.probe_details:
            print(
                "\n※ inquiry_closed は判別していない。詳細ページを開かないと\n"
                "  受付終了済みは検出できないため、実投入可能件数を出すには\n"
                "  --probe-details オプションで再実行する。"
            )
            return 0

        # --- 詳細プローブ ---
        listings_to_probe = list(unique.values())
        logger.info(
            "probing details for %d unique listings (no Claude API calls)",
            len(listings_to_probe),
        )
        open_count, closed_count, closed_ids = probe_closed(
            scraper, listings_to_probe, delay_seconds=delay
        )

    print("\n===== Detail probe =====")
    print(f"  ユニーク listing: {len(unique)}")
    print(f"  受付中 (投げ込み対象): {open_count}")
    print(f"  受付終了: {closed_count}")
    if closed_ids:
        print("\n  closed article_ids (先頭10件):")
        for aid in closed_ids[:10]:
            print(f"    - {aid}")
        if len(closed_ids) > 10:
            print(f"    ... and {len(closed_ids) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
