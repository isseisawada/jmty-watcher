"""ジモティの listing 総数を keyword ごとに計測する。

詳細ページは fetch しない。一覧ページを順次叩いて article_id を集合に貯めるだけ。
ネットワークアクセスはあるが、本番 watcher の登録対象が何件あるかの見積もりに使う。

使い方:
    uv run python -m watcher.count_jmty
    uv run python -m watcher.count_jmty --keywords トレーラーハウス,モバイルハウス
    uv run python -m watcher.count_jmty --max-pages 20

挙動:
- 取得件数が前ページと同じ article_id だけになったら（=ジモティが先頭ページに
  ループバックさせている兆候）打ち切る
- 0 件が返ってきたら打ち切る
- --max-pages で固い上限
- リクエスト間に WATCHER_REQUEST_DELAY_SECONDS の sleep を入れる（デフォルト 2.5s）

403/timeout が出る環境（GitHub Runner 等）では動かない。ローカル Mac から実行する。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .config import load_config
from .main import configure_logging
from .scraper import JmtyScraper

logger = logging.getLogger("count_jmty")


DEFAULT_KEYWORDS = ["トレーラーハウス"]


def count_keyword(
    scraper: JmtyScraper,
    keyword: str,
    *,
    max_pages: int,
    delay_seconds: float,
) -> tuple[int, int]:
    """(unique_article_count, pages_fetched) を返す。"""
    seen: set[str] = set()
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

        before = len(seen)
        for lst in listings:
            seen.add(lst.article_id)
        added = len(seen) - before
        logger.info(
            "  page %d: %d listings (unique +%d, total=%d)",
            page,
            len(listings),
            added,
            len(seen),
        )

        # 新規が増えなかった = 同じ結果がループしている → 打ち切り
        if added == 0:
            logger.info("page %d added 0 new article_ids → stop", page)
            break

        if page < max_pages:
            time.sleep(delay_seconds)

    return len(seen), page


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--keywords",
        default=None,
        help="カンマ区切り。未指定なら WATCHER_SEARCH_KEYWORDS or 'トレーラーハウス'",
    )
    p.add_argument("--max-pages", type=int, default=30)
    p.add_argument("--delay", type=float, default=None, help="ページ間 sleep 秒")
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
        "counting jmty listings: keywords=%s max_pages=%d delay=%.1fs",
        keywords,
        args.max_pages,
        delay,
    )

    union: set[str] = set()
    per_keyword: dict[str, int] = {}

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
            count, pages = count_keyword(
                scraper, kw, max_pages=args.max_pages, delay_seconds=delay
            )
            per_keyword[kw] = count
            # 全 keyword 横断のユニーク件数も貯める
            try:
                # 再 fetch せず、ここでは per-keyword 推定だけ表示。
                # ユニーク統合は精度のため別途実行する用途とし、ここでは合算のみ。
                union  # noqa: B018  (placeholder)
            except Exception:
                pass
            logger.info(
                "keyword=%s: %d unique listings in %d page(s)", kw, count, pages
            )
            if kw != keywords[-1]:
                time.sleep(delay)

    print("\n===== Summary =====")
    total = 0
    for kw, n in per_keyword.items():
        print(f"  {kw}: {n}")
        total += n
    print("  ------")
    print(f"  合計(重複あり可): {total}")
    print(
        "\n※ keyword間の重複は除いていない見積もり。実際の登録ユニーク数は\n"
        "   重複分（同じ article_id）が引かれた値になる。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
