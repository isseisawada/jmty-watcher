"""パイプライン全体のオフラインドライラン。

Supabase / Anthropic / Slack の認証なしで、

  - 一覧HTMLの解析
  - 詳細HTMLの解析（任意）
  - ダミー分類器による判定
  - ダミーDM生成
  - 「実際に投げたら」のSlackペイロード生成

までを一気通貫で実行する。実際のAPIは一切叩かない。
セレクタ修正・通知UI調整・パイプライン挙動確認に使用する想定。

使い方:
  uv run python -m watcher.offline_demo --listing tests/fixtures/listing_sample.html \
      --detail tests/fixtures/detail_sample.html
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from .models import Classification, DmDraft, Listing
from .scraper import JmtyScraper
from .slack_notifier import build_listing_blocks


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline pipeline dry-run")
    p.add_argument("--listing", type=Path, required=True, help="一覧HTMLファイル")
    p.add_argument(
        "--detail",
        type=Path,
        action="append",
        default=[],
        help="詳細HTMLファイル（複数指定可、article_id をファイル名に含めると対応付け）",
    )
    p.add_argument("--limit", type=int, default=5, help="表示する出品数")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("offline_output"),
        help="生成物（Slackペイロード等）の出力先",
    )
    return p.parse_args()


def fake_classify(listing: Listing) -> Classification:
    """価格・キーワードベースの単純なヒューリスティック分類器。

    実Claudeで判定する前に、パイプラインの形だけ通すためのもの。
    """
    title = (listing.title or "") + " " + (listing.snippet or "")
    is_trailer = True
    if any(kw in title for kw in ("レゴ", "デュプロ", "おもちゃ")):
        is_trailer = False
        return Classification(
            is_actual_trailer_house=False,
            seller_type="unknown",
            trailer_category="unknown",
            estimated_market_price_yen=None,
            price_gap_ratio=None,
            condition_grade="D",
            priority="C",
            concerns=["タイトルからおもちゃと判定"],
            sales_pitch_hook="",
            model_version="offline-fake",
        )
    if "ヒッチ" in title or "パーツ" in title:
        return Classification(
            is_actual_trailer_house=False,
            seller_type="unknown",
            trailer_category="unknown",
            estimated_market_price_yen=None,
            price_gap_ratio=None,
            condition_grade="D",
            priority="C",
            concerns=["パーツのみ"],
            sales_pitch_hook="",
            model_version="offline-fake",
        )

    price = listing.price_yen or 0
    estimated_market = max(price * 2, 5_000_000) if price > 0 else 6_000_000
    gap = (estimated_market - price) / max(price, 1) if price > 0 else 1.0

    if gap >= 0.3:
        priority = "S"
    elif gap >= 0.1:
        priority = "A"
    else:
        priority = "B"

    return Classification(
        is_actual_trailer_house=is_trailer,
        seller_type="individual",
        trailer_category="residential",
        estimated_market_price_yen=estimated_market,
        price_gap_ratio=round(gap, 3),
        condition_grade="B",
        priority=priority,
        concerns=["（オフラインモードのダミー懸念点）"],
        sales_pitch_hook=f"出品 {price:,}円 vs 推定相場 {estimated_market:,}円。妙味あり",
        model_version="offline-fake",
    )


def fake_dm(listing: Listing, classification: Classification) -> DmDraft:
    polite = (
        f"はじめまして。YADOKARIの澤田と申します。\n\n"
        f"{listing.title or 'トレーラーハウス'} の出品を拝見しました。"
        f"{classification.sales_pitch_hook}\n\n"
        f"弊社では中古トレーラーハウス専門サイト「TRAILER HOUSE SECOND HAND」を運営しております。"
        f"無料で出張査定・撮影・掲載代行も承っております。\n\n"
        f"ご興味あればご相談ください。\n"
        f"https://info.yadokari.net/form/usedtrailer_sale"
    )
    casual = polite.replace("ございます", "").replace("いたします", "します")
    return DmDraft(variant_polite=polite, variant_casual=casual, model_version="offline-fake")


def _find_detail_html(detail_paths: list[Path], article_id: str) -> Path | None:
    for p in detail_paths:
        if article_id in p.stem or p.stem in article_id:
            return p
    return None


def main() -> int:
    args = _parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    listing_html = args.listing.read_text(encoding="utf-8")
    scraper = JmtyScraper(user_agent="offline", request_delay_seconds=0)

    try:
        listings = list(scraper._parse_listing_html(listing_html))[: args.limit]
        for listing in listings:
            detail_path = _find_detail_html(args.detail, listing.article_id)
            if detail_path is not None:
                scraper._parse_detail_html(listing, detail_path.read_text(encoding="utf-8"))
    finally:
        scraper.close()

    today = date.today()
    print(f"=== Offline pipeline ({len(listings)} listings) ===\n")

    summary: list[dict] = []
    for listing in listings:
        # 詳細を取れていなければ「投稿日 = 3日前」のダミーを与える
        if listing.posted_date is None:
            listing.posted_date = today - timedelta(days=3)

        classification = fake_classify(listing)
        result_entry: dict = {
            "article_id": listing.article_id,
            "title": listing.title,
            "price_yen": listing.price_yen,
            "priority": classification.priority,
            "is_trailer": classification.is_actual_trailer_house,
            "estimated_market": classification.estimated_market_price_yen,
            "gap": classification.price_gap_ratio,
        }
        summary.append(result_entry)

        print(
            f"[{classification.priority}] {listing.article_id} "
            f"price={listing.price_yen} gap={classification.price_gap_ratio} "
            f"trailer={classification.is_actual_trailer_house} "
            f"hook={classification.sales_pitch_hook[:50]}"
        )

        # DM生成は S/A のみ
        if classification.priority in ("S", "A") and classification.is_actual_trailer_house:
            dm = fake_dm(listing, classification)
            (out_dir / f"dm_{listing.article_id}.txt").write_text(
                f"=== 丁寧版 ===\n{dm.variant_polite}\n\n=== フランク版 ===\n{dm.variant_casual}\n",
                encoding="utf-8",
            )

        # Slack通知ペイロード生成（投下はしない）
        if classification.priority in ("S", "A", "B"):
            blocks = build_listing_blocks(
                listing_id=f"offline-{listing.article_id}",
                listing=listing,
                classification=classification,
                days_since_posted=listing.days_since_posted(today),
            )
            (out_dir / f"slack_{listing.article_id}.json").write_text(
                json.dumps({"blocks": blocks}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    (out_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nWrote outputs → {out_dir}/")
    print("- _summary.json: 分類サマリ")
    print("- slack_*.json:  Slack Block Kit ペイロード（Block Kit Builderで確認可）")
    print("- dm_*.txt:      DM文案")
    print("\nサンプル listing 1件:")
    if listings:
        print(json.dumps(asdict(listings[0]), default=str, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
