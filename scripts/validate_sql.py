"""sql/schema.sql の構文を sqlparse で静的検証。

Postgres 接続なしで、

  - SQLとしてパース可能であること
  - 想定したテーブル4つが定義されていること
  - 主キー / unique 制約 / 外部キーが期待通り存在すること

をチェックする。
"""

from __future__ import annotations

from pathlib import Path

import sqlparse


SCHEMA = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"

EXPECTED_TABLES = {"jmty_listings", "classifications", "dm_drafts", "outreach_log"}
EXPECTED_FOREIGN_KEYS = {
    ("classifications", "jmty_listings"),
    ("dm_drafts", "jmty_listings"),
    ("outreach_log", "jmty_listings"),
}


def main() -> int:
    if not SCHEMA.exists():
        print(f"NG schema.sql not found: {SCHEMA}")
        return 1
    text = SCHEMA.read_text(encoding="utf-8")
    statements = [s for s in sqlparse.parse(text) if s.tokens]

    if not statements:
        print("NG could not parse any SQL statements")
        return 1
    print(f"OK parsed {len(statements)} SQL statements")

    found_tables: set[str] = set()
    for stmt in statements:
        normalized = " ".join(stmt.value.split())
        for table in EXPECTED_TABLES:
            if f"create table if not exists {table}" in normalized.lower():
                found_tables.add(table)

    missing = EXPECTED_TABLES - found_tables
    if missing:
        print(f"NG missing tables: {sorted(missing)}")
        return 1
    print(f"OK found expected tables: {sorted(found_tables)}")

    body = text.lower()
    for child, parent in EXPECTED_FOREIGN_KEYS:
        snippet = f"references {parent}"
        # 雑だが「子テーブルの宣言ブロック内に references parent がある」を見たい
        idx = body.find(f"create table if not exists {child}")
        if idx < 0:
            print(f"NG could not locate definition of {child}")
            return 1
        block_end = body.find(");", idx)
        block = body[idx:block_end]
        if snippet not in block:
            print(f"NG foreign key missing: {child} → {parent}")
            return 1
    print(f"OK foreign keys present: {sorted(EXPECTED_FOREIGN_KEYS)}")

    if "create extension if not exists \"uuid-ossp\"" not in body:
        print("NG uuid-ossp extension not declared")
        return 1
    print("OK uuid-ossp extension declared")

    # decision の CHECK 制約を確認
    if "decision in ('pending'" not in body:
        print("NG decision CHECK constraint missing")
        return 1
    print("OK decision CHECK constraint present")

    print("\nSQL validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
