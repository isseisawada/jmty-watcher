"""Slack Block Kit のプレビュー用ペイロードを生成。

ペイロードをファイル or stdout に出力するので、それを
https://app.slack.com/block-kit-builder に貼り付けると見た目を視覚確認できる。

    uv run python scripts/preview_slack.py                       # 通知メッセージのプレビュー
    uv run python scripts/preview_slack.py --modal               # DMモーダルのプレビュー
    uv run python scripts/preview_slack.py --out preview.json    # ファイル出力
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# パス調整: scripts/ から watcher パッケージを import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.models import Classification, Listing  # noqa: E402
from watcher.slack_notifier import build_listing_blocks  # noqa: E402


SAMPLE_LISTING = Listing(
    article_id="article-1o9e6w",
    url="https://jmty.jp/okinawa/sale-oth/article-1o9e6w",
    title="【築3年・超美品】6mトレーラーハウス／民泊・サロン・事務所に最適",
    price_yen=4_000_000,
    prefecture="沖縄",
    city="うるま市",
    category_label="その他",
    thumbnail_url="https://placehold.jp/600x400.png?text=Trailer+House",
    favorite_count=42,
)

SAMPLE_CLASSIFICATION = Classification(
    is_actual_trailer_house=True,
    seller_type="individual",
    trailer_category="residential",
    estimated_market_price_yen=6_500_000,
    price_gap_ratio=0.625,
    condition_grade="A",
    priority="S",
    concerns=[
        "写真が室内中心で外装・シャーシが確認できない",
        "沖縄からの輸送費要考慮",
    ],
    sales_pitch_hook="築3年・新品780万の物件が400万は破格で、SECOND HANDでも十分再販可能",
    model_version="claude-sonnet-4-6",
)

SAMPLE_DM_POLITE = (
    "はじめまして。YADOKARIの澤田と申します。\n\n"
    "築3年・6mの超美品というお写真を拝見しました。新品780万円の物件を400万円でというご提示、"
    "非常に良心的な価格設定だと感じております。\n\n"
    "弊社は日本初の中古トレーラーハウス専門サイト「TRAILER HOUSE SECOND HAND」を運営しており、"
    "全国の購入希望者にこの車両をマッチングできる可能性があります。ジモティより高い価格で売却"
    "できるケースも多く、無料で出張査定・撮影・掲載代行もお引き受けしております。\n\n"
    "もしご興味がございましたら、一度お話だけでもいかがでしょうか。\n\n"
    "▼ご相談窓口\nhttps://info.yadokari.net/form/usedtrailer_sale"
)

SAMPLE_DM_CASUAL = (
    "はじめまして。YADOKARIの澤田と申します。\n\n"
    "築3年・超美品6mのトレーラーハウス、お写真とても綺麗ですね。新品780万を400万でというのは"
    "正直、買い手がついてもおかしくない価格だと思いました。\n\n"
    "私たち、中古トレーラーハウス専門の「TRAILER HOUSE SECOND HAND」というサイトをやっていて、"
    "ジモティ以外でも全国の検討者に紹介できます。出張査定・撮影・掲載までこちらで無料で動きます。\n\n"
    "もしジモティで決まらなければ、お気軽にご相談ください。\n"
    "https://info.yadokari.net/form/usedtrailer_sale"
)


def build_listing_preview() -> dict:
    blocks = build_listing_blocks(
        listing_id="00000000-0000-0000-0000-000000000001",
        listing=SAMPLE_LISTING,
        classification=SAMPLE_CLASSIFICATION,
        days_since_posted=4,
    )
    return {"blocks": blocks}


def build_modal_preview() -> dict:
    return {
        "type": "modal",
        "callback_id": "dm_modal",
        "title": {"type": "plain_text", "text": "DM文案", "emoji": True},
        "close": {"type": "plain_text", "text": "閉じる"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*対象出品*: <{SAMPLE_LISTING.url}|{SAMPLE_LISTING.title}>",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*丁寧版*\n```{SAMPLE_DM_POLITE}```"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "approve_polite",
                        "text": {"type": "plain_text", "text": "丁寧版を採用してコピー"},
                        "style": "primary",
                    }
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*フランク版*\n```{SAMPLE_DM_CASUAL}```"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "approve_casual",
                        "text": {"type": "plain_text", "text": "フランク版を採用してコピー"},
                        "style": "primary",
                    }
                ],
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Slack Block Kit プレビュー")
    parser.add_argument("--modal", action="store_true", help="モーダルのプレビューを出力")
    parser.add_argument("--out", type=Path, default=None, help="出力先ファイル")
    args = parser.parse_args()

    payload = build_modal_preview() if args.modal else build_listing_preview()
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)

    if not args.out:
        print(
            "\n# 確認方法:\n"
            "# 1. 上記JSONをコピー\n"
            "# 2. https://app.slack.com/block-kit-builder にペースト\n"
            "# 3. レンダリング結果を視覚確認",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
