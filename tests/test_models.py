"""Listing.to_db_row() が jmty_listings スキーマと整合していること。"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from watcher.models import Listing


def _schema_columns(table: str) -> set[str]:
    """sql/schema.sql から `create table <table>` のカラム名を抽出。"""
    sql = Path(__file__).resolve().parent.parent.joinpath("sql/schema.sql").read_text()
    m = re.search(
        rf"create\s+table\s+if\s+not\s+exists\s+{table}\s*\((.*?)\);",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert m, f"{table} の CREATE TABLE が schema.sql に見つからない"
    body = m.group(1)
    cols: set[str] = set()
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        # 制約行・カラム以外をスキップ
        first = line.split()[0].lower()
        if first in {"primary", "constraint", "check", "unique", "foreign", "references"}:
            continue
        # `column_name type ...` の最初のトークンがカラム名
        cols.add(first)
    return cols


def _full_listing() -> Listing:
    return Listing(
        article_id="article-test",
        url="https://jmty.jp/x/sale/article-test",
        title="トレーラーハウス売ります",
        price_yen=1_500_000,
        prefecture="千葉",
        city="柏市",
        category_label="その他",
        thumbnail_url="https://img.cdn.jmty.jp/x.jpg",
        snippet="広い庭付き",
        created_at_text="2日前",
        updated_at_text="1日前",
        favorite_count=3,
        description_full="本文" * 20,
        image_urls=["https://img.cdn.jmty.jp/1.jpg"],
        seller_name="山田",
        seller_type_hint="individual",
        seller_post_count=4,
        posted_date=date(2026, 5, 19),
        last_updated_date=date(2026, 5, 20),
        view_count=120,
    )


def test_to_db_row_only_emits_columns_present_in_schema() -> None:
    schema_cols = _schema_columns("jmty_listings")
    row = _full_listing().to_db_row()
    unknown = set(row.keys()) - schema_cols
    assert not unknown, (
        f"to_db_row() が jmty_listings に存在しないカラムを返している: {unknown}\n"
        f"schema columns: {sorted(schema_cols)}"
    )


def test_to_db_row_drops_transient_listing_page_text_fields() -> None:
    row = _full_listing().to_db_row()
    # 一覧ページから拾った生テキストはDB保存対象外
    assert "snippet" not in row
    assert "created_at_text" not in row
    assert "updated_at_text" not in row


def test_to_db_row_serializes_dates_as_iso_strings() -> None:
    row = _full_listing().to_db_row()
    assert row["posted_date"] == "2026-05-19"
    assert row["last_updated_date"] == "2026-05-20"
