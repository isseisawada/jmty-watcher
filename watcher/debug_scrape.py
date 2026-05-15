"""スクレイパー単体デバッグ用。

ネットワークアクセス不要のオフラインモード対応:
    --from-html PATH       一覧HTMLファイルから解析
    --detail-html PATH     詳細HTMLファイル（複数指定可）の解析もあわせて

通常モード:
    uv run python -m watcher.debug_scrape                       # 一覧のみ
    uv run python -m watcher.debug_scrape --details 3           # 上位3件は詳細も
    uv run python -m watcher.debug_scrape --keyword モバイルハウス
    uv run python -m watcher.debug_scrape --save-html out/      # 生HTMLも保存
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

from .models import Listing
from .scraper import LISTING_URL_TEMPLATE, JmtyScraper

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jimoty scraper debug runner")
    p.add_argument("--keyword", default="トレーラーハウス")
    p.add_argument("--details", type=int, default=0, help="ネット取得時、詳細ページもfetchする件数")
    p.add_argument("--delay", type=float, default=2.5)
    p.add_argument(
        "--save-html",
        type=Path,
        default=None,
        help="指定ディレクトリに一覧/詳細の生HTMLを保存",
    )
    p.add_argument("--limit", type=int, default=30, help="一覧の表示上限")
    p.add_argument(
        "--from-html",
        type=Path,
        default=None,
        help="一覧ページのローカル保存HTMLを解析（ネットアクセスなし）",
    )
    p.add_argument(
        "--detail-html",
        type=Path,
        action="append",
        default=[],
        help="詳細ページのローカル保存HTMLを解析（複数指定可）",
    )
    return p.parse_args()


def _fmt_price(v: int | None) -> str:
    return f"{v:,}" if v is not None else "—"


def _print_listing_table(listings: list[Listing]) -> None:
    header = f"{'article_id':<18} {'price':>10}  {'pref':<8} {'city':<12} title"
    print(header)
    print("-" * len(header))
    for l in listings:
        title = (l.title or "")[:50]
        print(
            f"{l.article_id:<18} {_fmt_price(l.price_yen):>10}  "
            f"{(l.prefecture or '-'):<8} {(l.city or '-'):<12} {title}"
        )


def _missing_field_report(listings: list[Listing]) -> None:
    print("\n== 欠損率チェック (一覧段階) ==")
    total = len(listings) or 1
    fields = ["title", "price_yen", "prefecture", "city", "thumbnail_url", "snippet"]
    for f in fields:
        missing = sum(1 for l in listings if getattr(l, f) in (None, "", 0))
        pct = missing * 100 // total
        flag = "⚠️ " if pct >= 30 else "   "
        print(f"{flag}{f:<16} 欠損 {missing:>3}/{total:<3} ({pct}%)")


def _run_from_html(args: argparse.Namespace) -> int:
    listing_path: Path = args.from_html
    if not listing_path.exists():
        print(f"file not found: {listing_path}")
        return 1
    html = listing_path.read_text(encoding="utf-8")

    # ネットワーク無しのため scraper.client は使わずパース関数だけ呼ぶ。
    scraper = JmtyScraper(user_agent=DEFAULT_UA, request_delay_seconds=args.delay)
    try:
        listings = list(scraper._parse_listing_html(html))[: args.limit]
    finally:
        scraper.close()

    print(f"parsed {len(listings)} listings from {listing_path}\n")
    _print_listing_table(listings)
    _missing_field_report(listings)

    if args.detail_html:
        scraper = JmtyScraper(user_agent=DEFAULT_UA, request_delay_seconds=args.delay)
        try:
            print(f"\n== 詳細ページ解析 ({len(args.detail_html)} ファイル) ==")
            for detail_path in args.detail_html:
                if not detail_path.exists():
                    print(f"- {detail_path}: file not found")
                    continue
                detail_html = detail_path.read_text(encoding="utf-8")
                # listing がなければダミーを作って詳細だけ解析
                target = _find_listing_for_detail(listings, detail_path) or Listing(
                    article_id=detail_path.stem,
                    url="",
                    title="",
                    price_yen=None,
                    prefecture=None,
                    city=None,
                    category_label=None,
                    thumbnail_url=None,
                )
                scraper._parse_detail_html(target, detail_html)
                print(
                    f"- {detail_path.name}: "
                    f"desc={len(target.description_full or '')} chars, "
                    f"images={len(target.image_urls)}, "
                    f"posted={target.posted_date}, "
                    f"seller_hint={target.seller_type_hint}"
                )
            sample = _find_listing_for_detail(listings, args.detail_html[0]) or listings[0]
            print("\n== サンプル1件の全フィールド ==")
            print(json.dumps(asdict(sample), default=str, ensure_ascii=False, indent=2))
        finally:
            scraper.close()
    return 0


def _find_listing_for_detail(listings: list[Listing], detail_path: Path) -> Listing | None:
    stem = detail_path.stem
    for l in listings:
        if l.article_id in stem or stem in l.article_id:
            return l
    return None


def _run_live(args: argparse.Namespace) -> int:
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

        if args.details > 0 and listings:
            print(f"\n== 詳細ページ取得 (上位 {args.details} 件) ==")
            for listing in listings[: args.details]:
                try:
                    time.sleep(args.delay)
                    r = scraper.client.get(listing.url)
                    r.raise_for_status()
                    if out_dir:
                        (out_dir / f"{listing.article_id}.html").write_text(
                            r.text, encoding="utf-8"
                        )
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


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    args = _parse_args()

    if args.from_html:
        return _run_from_html(args)
    return _run_live(args)


if __name__ == "__main__":
    raise SystemExit(main())
