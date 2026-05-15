"""月額コスト試算スクリプト。

実プロンプトテンプレートにダミー値を埋めた長さからトークン数を概算し、
1時間毎×24×30 実行を前提に月額を算出。
モデル単価は2026年5月時点の Claude Sonnet 4.6 公開価格を埋め込み（変動するので注意）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.anthropic_utils import load_prompt, render  # noqa: E402

# Claude Sonnet 4.6 の公開価格 (USD per 1M tokens, 2026-05時点目安)
PRICE_INPUT_PER_M = 3.0
PRICE_OUTPUT_PER_M = 15.0
PRICE_INPUT_CACHE_HIT_PER_M = 0.30
USD_TO_JPY = 155.0

# 標準的なジモティ出品をモデル化。実データ平均より少し長めに見積もる。
DUMMY_LISTING = {
    "title": "【築3年・超美品】6mトレーラーハウス／民泊・サロン・事務所に最適です",
    "price_yen": 4_000_000,
    "prefecture": "沖縄",
    "city": "うるま市",
    "category_label": "その他",
    "description_full": (
        "新品時780万円のトレーラーハウスを大切に使用しておりました。"
        "築3年で内外装ともに極上の状態です。エアコン・キッチン・トイレ・シャワー完備。"
        "民泊・サロン・事務所・グランピング施設としての利用に最適。"
        "沖縄県内であれば配送相談可能。"
    ) * 4,  # 平均的な長文出品を想定
    "posted_date": "2026-04-07",
    "days_since_posted": 30,
    "favorite_count": 42,
    "seller_name": "沖縄太郎",
    "seller_type_hint": "individual",
    "priority": "S",
    "estimated_market_price_yen": 6_500_000,
    "sales_pitch_hook": "築3年で破格、SECOND HAND再販可能",
    "seller_type": "individual",
    "description_snippet": "築3年・新品780万のトレーラーハウス",
    "inquiry_url": "https://info.yadokari.net/form/usedtrailer_sale",
}

# 画像をbase64で渡すとトークンを大量に消費する。Claudeの画像トークン換算: 約1.6 tokens / 1000 pixels。
# 標準的な ジモティ画像 (1024x768) を3枚と仮定。
IMAGE_TOKENS_PER_RUN = int(1024 * 768 / 1000 * 1.6) * 3


def approx_tokens(text: str) -> int:
    """ざっくり 1 token ≈ 2.5 文字（日本語ヘビーな前提）。"""
    return int(len(text) / 2.5) + 4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--listings-per-run",
        type=int,
        default=10,
        help="1実行で classifier に投げる平均件数（新規のみ）",
    )
    parser.add_argument(
        "--dm-per-run", type=int, default=2, help="1実行で DM生成する平均件数（S/A）"
    )
    parser.add_argument(
        "--runs-per-month", type=int, default=24 * 30, help="月の実行回数（毎時×30日 = 720）"
    )
    args = parser.parse_args()

    classifier_prompt = render(load_prompt("classifier"), **DUMMY_LISTING)
    dm_prompt = render(load_prompt("dm_generator"), **DUMMY_LISTING)

    classifier_input_tokens = approx_tokens(classifier_prompt) + IMAGE_TOKENS_PER_RUN
    classifier_output_tokens = 350  # JSON応答の想定
    dm_input_tokens = approx_tokens(dm_prompt)
    dm_output_tokens = 600  # 2バリエーション分

    print("== Per-call token estimate ==")
    print(f"classifier  input  ≈ {classifier_input_tokens:>6} tokens "
          f"(image≈{IMAGE_TOKENS_PER_RUN}, text≈{classifier_input_tokens - IMAGE_TOKENS_PER_RUN})")
    print(f"classifier  output ≈ {classifier_output_tokens:>6} tokens")
    print(f"dm_generator input  ≈ {dm_input_tokens:>6} tokens")
    print(f"dm_generator output ≈ {dm_output_tokens:>6} tokens")

    classifier_calls = args.listings_per_run * args.runs_per_month
    dm_calls = args.dm_per_run * args.runs_per_month

    classifier_in_total = classifier_input_tokens * classifier_calls
    classifier_out_total = classifier_output_tokens * classifier_calls
    dm_in_total = dm_input_tokens * dm_calls
    dm_out_total = dm_output_tokens * dm_calls

    in_total = classifier_in_total + dm_in_total
    out_total = classifier_out_total + dm_out_total

    cost_usd = (in_total / 1_000_000) * PRICE_INPUT_PER_M + (
        out_total / 1_000_000
    ) * PRICE_OUTPUT_PER_M
    cost_jpy = cost_usd * USD_TO_JPY

    print("\n== Monthly volume ==")
    print(f"runs/month       : {args.runs_per_month}")
    print(f"classifier calls : {classifier_calls:,}")
    print(f"dm_generator calls: {dm_calls:,}")
    print(f"total input  tokens: {in_total:>12,}")
    print(f"total output tokens: {out_total:>12,}")

    print("\n== Monthly cost (no caching) ==")
    print(f"USD: ${cost_usd:,.2f}")
    print(f"JPY: ¥{cost_jpy:,.0f}  (at ¥{USD_TO_JPY}/USD)")

    # prompt caching でclassifierの定型部分は割引可能
    cached_text = classifier_prompt.split("【出品情報】")[0]  # 定型ヘッダだけがキャッシュ可能と仮定
    cached_tokens = approx_tokens(cached_text)
    cache_savings_per_call = (
        cached_tokens * (PRICE_INPUT_PER_M - PRICE_INPUT_CACHE_HIT_PER_M) / 1_000_000
    )
    monthly_cache_savings_usd = cache_savings_per_call * classifier_calls
    print("\n== With prompt caching (classifier定型ヘッダ) ==")
    print(f"cacheable tokens/call ≈ {cached_tokens}")
    print(f"savings              : ${monthly_cache_savings_usd:,.2f}/月 "
          f"≈ ¥{monthly_cache_savings_usd * USD_TO_JPY:,.0f}")
    print(f"net monthly cost     : ¥{(cost_jpy - monthly_cache_savings_usd * USD_TO_JPY):,.0f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
