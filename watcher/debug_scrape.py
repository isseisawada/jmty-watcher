"""スクレイパー単体デバッグ用。

Secrets は一切不要。一覧ページを取得して article_id / title / price_yen /
prefecture / city / thumbnail_url が埋まっているかを確認するためのスクリプト。

    uv run python -m watcher.debug_scrape                       # 一覧のみ
    uv run python -m watcher.debug_scrape --details 3           # 上位3件は詳細も
    uv run python -m watcher.debug_scrape --keyword モバイルハウス
    uv run python -m watcher.debug_scrape --save-html out/      # 生HTMLも保存

出力は人間が眺めて欠損セレクタを特定する目的のため、テーブル形式＋JSON。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.parse
from dataclasses import asdict
from pathlib import Path

from .scraper import JMTY_BASE, LISTING_URL_TEMPLATE, JmtyScraper

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jimoty scraper debug runner")
    p.add_argument("--keyword", default="トレーラーハウス")
    p.add_argument("--details", type=int, default=0, help="詳細ページもfetchする件数")
    p.add_argument("--delay", type=float, default=2.5)
    p.add_argument("--save-html", type=Path, default=None,
                   help="指定ディレクトリに一覧/詳細の生HTMLを保存")
    p.add_argument("--limit", type=int, default=30, help="一覧の表示上限")
    return p.parse_args()


def _fmt_price(v: int | None) -> str:
    return f"{v:,}" if v is not None else "—"


def _print_listing_table(listings: list) -> None:
    header = f"{'article_id':<18} {'price':>10}  {'pref':<8} {'city':<12} title"
    print(header)
    print("-" * len(header))
    for l in listings:
        title = (l.title or "")[:50]
        print(
            f"{l.article_id:<18} {_fmt_price(l.price_yen):>10}  "
            f"{(l.prefecture or '-'):<8} {(l.city or '-'):<12} {title}"
        )


def _missing_field_report(listings: list) -> None:
    print("\n== 欠損率チェック (一覧段階) ==")
    total = len(listings) or 1
    fields = ["title", "price_yen", "prefecture", "city", "thumbnail_url", "snippet"]
    for f in fields:
        missing = sum(1 for l in listings if getattr(l, f) in (None, "", 0))
        pct = missing * 100 // total
        flag = "⚠️ " if pct >= 30 else "   "
        print(f"{flag}{f:<16} 欠損 {missing:>3}/{total:<3} ({pct}%)")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    args = _parse_args()

    out_dir: Path | None = None
    if args.save_html:
        out_dir = args.save_html
        out_dir.mkdir(parents=True, exist_ok=True)

    with JmtyScraper(user_agent=DEFAULT_UA, request_delay_seconds=args.delay) as scraper:
        if not scraper.check_robots_allowed():
            print("robots.txt disallows scraping — aborting")
            return 1

        listing_url = LISTING_URL_TEMPLATE.format(keyword=urllib.parse.quote(args.keyword))
        print(f"fetching: {listing_url}\n")
        resp = scraper.client.get(listing_url)
        resp.raise_for_status()
        if out_dir:
            (out_dir / "listing.html").write_text(resp.text, encoding="utf-8")
            print(f"(saved listing HTML → {out_dir / 'listing.html'})")

        listings = list(scraper._parse_listing_html(resp.text))[: args.limit]
        print(f"parsed {len(listings)} listings\n")

        _print_listing_table(listings)
        _missing_field_report(listings)

        if args.details > 0:
            print(f"\n== 詳細ページ取得 (上位 {args.details} 件) ==")
            for listing in listings[: args.details]:
                try:
                    time.sleep(args.delay)
                    r = scraper.client.get(listing.url)
                    r.raise_for_status()
                    if out_dir:
                        (out_dir / f"{listing.article_id}.html").write_text(r.text, encoding="utf-8")
                    scraper._parse_detail_html(listing, r.text)
                    print(
                        f"- {listing.article_id}: "
                        f"desc={len(listing.description_full or '')} chars, "
                        f"images={len(listing.image_urls)}, "
                        f"posted={listing.posted_date}, "
                        f"seller_hint={listing.seller_type_hint}"
                    )
                except Exception as e:
                    print(f"- {listing.article_id}: ERROR {e}")

            print("\n== サンプル1件の全フィールド ==")
            print(json.dumps(asdict(listings[0]), default=str, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
