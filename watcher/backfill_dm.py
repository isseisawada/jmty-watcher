"""DM 草案が未生成の listing に対して DM を後追い生成する。

想定ユースケース:
- DM_PRIORITIES の対象を拡大したとき（例: {S,A} → {S,A,B}）
- dm_generator の一時的失敗で抜けた listing を再試行したいとき

idempotent: 既に dm_drafts に行がある listing は対象外。
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .db import Db
from .dm_generator import DmGenerator
from .main import DM_PRIORITIES, configure_logging
from .models import Classification, Listing

logger = logging.getLogger("backfill_dm")


def find_targets(
    db: Db,
    priorities: set[str],
) -> list[tuple[str, Listing, Classification]]:
    """(listing_id, Listing, Classification) のタプル列を返す。"""
    listing_ids_with_dm = db.list_listing_ids_with_dm_draft()
    rows = db.list_all_listing_rows()
    out: list[tuple[str, Listing, Classification]] = []
    for row in rows:
        if row.get("inquiry_closed"):
            continue  # 受付終了済みは DM 生成不要
        listing_id = row["id"]
        if listing_id in listing_ids_with_dm:
            continue
        c_row = db.get_latest_classification_row(listing_id)
        if c_row is None:
            continue
        if c_row.get("priority") not in priorities:
            continue
        out.append(
            (listing_id, Listing.from_db_row(row), Classification.from_db_row(c_row))
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="対象を列挙するだけで DM 生成は行わない",
    )
    parser.add_argument(
        "--priorities",
        default=",".join(sorted(DM_PRIORITIES)),
        help="対象 priority（カンマ区切り、デフォルト: 本番と同じ）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="生成する最大件数（安全弁）",
    )
    args = parser.parse_args(argv)

    configure_logging()
    cfg = load_config()
    db = Db(cfg.supabase_url, cfg.supabase_key)

    priorities = {p.strip() for p in args.priorities.split(",") if p.strip()}
    targets = find_targets(db, priorities)
    if args.limit is not None:
        targets = targets[: args.limit]

    logger.info(
        "backfill targets: %d listing(s) (priorities=%s, dry_run=%s)",
        len(targets),
        sorted(priorities),
        args.dry_run,
    )
    for listing_id, listing, classification in targets:
        logger.info(
            "  - %s [%s] %s",
            classification.priority,
            listing.article_id,
            (listing.title or "")[:60],
        )

    if args.dry_run or not targets:
        return 0

    dm_generator = DmGenerator(
        cfg.anthropic_api_key, cfg.dm_model, cfg.yadokari_inquiry_url
    )

    success = 0
    failures: list[str] = []
    for listing_id, listing, classification in targets:
        try:
            draft = dm_generator.generate(listing, classification)
            db.upsert_dm_draft(listing_id, draft)
            success += 1
            logger.info("generated DM for %s", listing.article_id)
        except Exception as e:  # noqa: BLE001
            failures.append(listing.article_id)
            logger.exception("DM generation failed for %s: %s", listing.article_id, e)

    logger.info(
        "done: %d/%d succeeded (failures=%s)", success, len(targets), failures
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
