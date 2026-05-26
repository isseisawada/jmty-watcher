"""sandwich() がヘッダー/フッターで中段を挟むこと、Claude レスポンス
parsing が body キーから middle を取り出すこと。"""

from __future__ import annotations

from unittest.mock import MagicMock

from watcher.dm_generator import DM_FOOTER, DM_HEADER, DmGenerator, sandwich
from watcher.models import Classification, Listing


def _listing() -> Listing:
    return Listing(
        article_id="article-1junmn",
        url="https://jmty.jp/kagoshima/sale-oth/article-1junmn",
        title="トレーラーハウス　事務所や店舗等にいかがですか？",
        price_yen=2_750_000,
        prefecture="鹿児島",
        city="鹿児島市",
        category_label="その他",
        thumbnail_url="https://img.cdn.jmty.jp/x.jpg",
        description_full="本文",
    )


def _classification() -> Classification:
    return Classification(
        is_actual_trailer_house=True,
        seller_type="individual",
        trailer_category="commercial",
        estimated_market_price_yen=3_200_000,
        price_gap_ratio=0.16,
        condition_grade="B",
        priority="A",
        concerns=["輸送費要確認"],
        sales_pitch_hook="事業用途で需要あり",
        model_version="x",
    )


def test_sandwich_wraps_middle_with_header_and_footer() -> None:
    out = sandwich("段落1の本文\n\n段落2の本文")
    assert out.startswith(DM_HEADER)
    assert out.endswith(DM_FOOTER)
    assert "段落1の本文" in out
    assert "段落2の本文" in out
    # ヘッダーと中段、中段とフッター それぞれ空行1行で区切られている
    assert "ご連絡しました！\n\n段落1の本文" in out
    assert "段落2の本文\n\n▶ TRAILER HOUSE SECOND HAND掲載情報提出フォーム" in out


def test_sandwich_strips_leading_trailing_whitespace_from_middle() -> None:
    out = sandwich("\n\n  段落本文  \n\n")
    # 中段の余分な空白は落とされ、区切り改行は常に一定
    assert out.count("\n\n  段落本文") == 0  # 先頭空白が消されている
    assert "ご連絡しました！\n\n段落本文" in out


def test_header_includes_exclamation_mark() -> None:
    """ヘッダー末尾の `！` が含まれていること（ユーザー指定の文言）。"""
    assert DM_HEADER.endswith("ご連絡しました！")


def test_footer_has_three_resource_links() -> None:
    """フッターは3つのリソース URL を含む。"""
    assert "info.yadokari.net/form/usedtrailer_sale_information" in DM_FOOTER
    assert "yadokari.net/2nd/" in DM_FOOTER
    assert "yadokari.company/" in DM_FOOTER


def test_generate_returns_dm_with_header_middle_footer() -> None:
    """Claude の JSON 出力（body キー）から DmDraft.variant_polite を構築。
    variant_casual は廃止（空文字）。"""

    fake_response = MagicMock()
    fake_response.content = [
        MagicMock(
            type="text",
            text='{"body": "鹿児島での「事務所や店舗等...」というご出品...\\n\\n（残り段落）"}',
        )
    ]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    gen = DmGenerator(api_key="x", model="claude-sonnet-4-6", inquiry_url="https://x")
    gen.client = fake_client

    draft = gen.generate(_listing(), _classification())

    assert draft.model_version == "claude-sonnet-4-6"
    # ヘッダー + 中段 + フッター が並ぶ
    assert draft.variant_polite.startswith(DM_HEADER)
    assert draft.variant_polite.endswith(DM_FOOTER)
    assert "鹿児島での「事務所や店舗等" in draft.variant_polite
    # variant_casual は使わない方針
    assert draft.variant_casual == ""


def test_generate_raises_on_empty_body() -> None:
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text='{"body": ""}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    gen = DmGenerator(api_key="x", model="x", inquiry_url="x")
    gen.client = fake_client

    try:
        gen.generate(_listing(), _classification())
    except ValueError as e:
        assert "empty" in str(e).lower()
    else:
        raise AssertionError("ValueError 期待")
