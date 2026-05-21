"""既に DB にいる listing をスプシに後追い追加する。

priority 拡張時の追加対象や、SHEETS_WEBHOOK 設定前に DB だけ進んでしまった
listing を埋めるためのバックフィル。Apps Script 側で article_id 重複チェックが
効くので、同じ listing を再送しても二重登録は発生しない（idempotent）。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from .config import load_config
from .db import Db
from .main import NOTIFY_PRIORITIES, configure_logging
from .models import Classification, Listing
from .sheets_notifier import SheetsNotifier

logger = logging.getLogger("backfill_sheets")


def find_targets(
    db: Db,
    priorities: set[str],
) -> list[tuple[str, Listing, Classification]]:
    """(listing_id, Listing, Classification) のタプル列を返す。"""
    rows = db.list_all_listing_rows()
    out: list[tuple[str, Listing, Classification]] = []
    for row in rows:
        if row.get("inquiry_closed"):
            continue  # 受付終了済みはスプシ非対象
        listing_id = row["id"]
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
        help="対象列挙のみで送信はしない",
    )
    parser.add_argument(
        "--priorities",
        default=",".join(sorted(NOTIFY_PRIORITIES)),
        help="対象 priority（カンマ区切り、デフォルト: 本番通知と同じ）",
    )
    parser.add_argument("--limit", type=int, default=None, help="送信件数の上限")
    args = parser.parse_args(argv)

    configure_logging()
    cfg = load_config()

    if not cfg.sheets_webhook_url:
        logger.error(
            "SHEETS_WEBHOOK_URL is not set. docs/google_sheets_setup.md を参照"
        )
        return 1

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
    for _listing_id, listing, classification in targets:
        logger.info(
            "  - %s [%s] %s",
            classification.priority,
            listing.article_id,
            (listing.title or "")[:60],
        )

    if args.dry_run or not targets:
        return 0

    today = date.today()
    success = 0
    failures: list[str] = []
    with SheetsNotifier(cfg.sheets_webhook_url, cfg.sheets_webhook_token) as sheets:
        for listing_id, listing, classification in targets:
            draft = db.get_dm_draft(listing_id)
            dm_polite = draft.variant_polite if draft else None
            if sheets.append_listing(
                listing=listing,
                classification=classification,
                dm_polite=dm_polite,
                days_since_posted=listing.days_since_posted(today),
            ):
                success += 1
            else:
                failures.append(listing.article_id)

    logger.info(
        "done: %d/%d succeeded (failures=%s)", success, len(targets), failures
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
