-- Supabase schema for second-hand-watcher
-- Run once on a fresh Supabase project.

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------------------
-- jmty_listings: one row per Jimoty article_id. Upserted every run.
-- ---------------------------------------------------------------------------
create table if not exists jmty_listings (
    id                 uuid primary key default uuid_generate_v4(),
    article_id         text not null unique,
    url                text not null,
    title              text,
    price_yen          bigint,
    prefecture         text,
    city               text,
    category_label     text,
    thumbnail_url      text,
    description_full   text,
    image_urls         jsonb default '[]'::jsonb,
    seller_name        text,
    seller_type_hint   text,
    seller_post_count  int,
    posted_date        date,
    last_updated_date  date,
    favorite_count     int,
    view_count         int,
    inquiry_closed     boolean not null default false,
    raw_html           text,
    first_seen_at      timestamptz not null default now(),
    last_checked_at    timestamptz not null default now()
);

create index if not exists jmty_listings_first_seen_at_idx
    on jmty_listings (first_seen_at desc);

-- ---------------------------------------------------------------------------
-- classifications: AI judgement history. Append-only; latest row wins.
-- ---------------------------------------------------------------------------
create table if not exists classifications (
    id                         uuid primary key default uuid_generate_v4(),
    listing_id                 uuid not null references jmty_listings(id) on delete cascade,
    is_actual_trailer_house    boolean,
    seller_type                text,
    trailer_category           text,
    estimated_market_price_yen bigint,
    price_gap_ratio            numeric,
    condition_grade            text,
    priority                   text,
    concerns                   jsonb default '[]'::jsonb,
    sales_pitch_hook           text,
    raw_response               jsonb,
    model_version              text,
    classified_at              timestamptz not null default now()
);

create index if not exists classifications_listing_id_idx
    on classifications (listing_id, classified_at desc);

-- ---------------------------------------------------------------------------
-- dm_drafts: generated DM variants. One row per listing (upsert keyed by listing_id).
-- ---------------------------------------------------------------------------
create table if not exists dm_drafts (
    id                 uuid primary key default uuid_generate_v4(),
    listing_id         uuid not null unique references jmty_listings(id) on delete cascade,
    variant_polite     text,
    variant_casual     text,
    model_version      text,
    created_at         timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- outreach_log: records user decisions on each Slack notification.
-- ---------------------------------------------------------------------------
create table if not exists outreach_log (
    id               uuid primary key default uuid_generate_v4(),
    listing_id       uuid not null references jmty_listings(id) on delete cascade,
    slack_channel_id text,
    slack_message_ts text,
    decision         text check (decision in ('pending', 'approved', 'edited', 'rejected')),
    final_dm_text    text,
    decided_at       timestamptz,
    decided_by       text,
    created_at       timestamptz not null default now()
);

create index if not exists outreach_log_listing_id_idx
    on outreach_log (listing_id, created_at desc);
