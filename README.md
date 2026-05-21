# second-hand-watcher (PoC)

ジモティーに出品される中古トレーラーハウスを自動監視し、仕入れ妙味のある案件を Slack に通知。承認された案件に対してパーソナライズ DM 文を自動生成し、クリップボードコピーで手動送信できる状態にする。

## 構成

```
GitHub Actions (cron毎時)
 ├─ watcher/scraper.py      ジモティ一覧＋詳細ページ取得
 ├─ watcher/classifier.py   Claude Sonnet 4.6で妙味判定（S/A/B/C）
 ├─ watcher/dm_generator.py 優先度S/AのDM文（丁寧版/フランク版）生成
 ├─ watcher/db.py           Supabase保存
 └─ watcher/slack_notifier.py Block Kitで通知

Vercel Serverless
 └─ handler/api/slack_interactive.py  モーダル表示 + 承認/スルー処理
```

## セットアップ

### 1. Supabase

新規プロジェクトを作り、SQL Editor で `sql/schema.sql` を実行。
Service Role Key を控える（RLSを使わない場合でも Service Key が必要）。

### 2. Slack App

1. <https://api.slack.com/apps> で App を作成
2. **OAuth & Permissions** → `chat:write`, `chat:write.public` を付与して install → Bot Token を取得
3. **Interactivity & Shortcuts** をオン → Request URL を `https://<vercel-app>.vercel.app/api/slack/interactive` に設定
4. **Basic Information** → Signing Secret を控える
5. 通知先チャンネルに Bot を招待し、チャンネル ID を控える

### 3. 環境変数

GitHub Actions の Secrets と Vercel の Environment Variables に以下を登録。

| 変数 | 用途 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API |
| `SUPABASE_URL` | Supabase プロジェクト URL |
| `SUPABASE_SERVICE_KEY` | Supabase Service Role Key |
| `SLACK_BOT_TOKEN` | `xoxb-...` |
| `SLACK_CHANNEL_ID` | 通知先チャンネル |
| `SLACK_SIGNING_SECRET` | **Vercelのみ**（ハンドラで署名検証） |
| `YADOKARI_INQUIRY_URL` | DM文末尾の問い合わせフォーム |

任意 (GitHub Actions Variables で上書き可):

| 変数 | 既定値 |
| --- | --- |
| `WATCHER_CLASSIFIER_MODEL` | `claude-sonnet-4-6` |
| `WATCHER_DM_MODEL` | `claude-sonnet-4-6` |
| `WATCHER_SEARCH_KEYWORDS` | `トレーラーハウス` (カンマ区切りで複数可) |
| `WATCHER_MAX_DETAILS_PER_RUN` | `30` |
| `WATCHER_REQUEST_DELAY_SECONDS` | `2.5` |
| `WATCHER_DRY_RUN` | `false` |

### 4. ローカル実行

```bash
uv sync
cp .env.example .env  # 値を埋める
uv run python -m watcher.main
```

初回は DB に既存案件がないため最大 `WATCHER_MAX_DETAILS_PER_RUN` 件まで詳細 fetch + 判定が走る。

### 5. Vercel デプロイ（インタラクティブハンドラ）

```bash
cd handler
vercel --prod
```

Environment Variables に `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` / `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` を設定。

### 6. GitHub Actions

`.github/workflows/watcher.yml` を配置済み。Secrets 登録後、**Actions** タブから `Second Hand Watcher` を手動実行して動作確認 → 問題なければ cron で自動稼働。

## 開発支援ツール

| コマンド | 用途 |
| --- | --- |
| `uv run pytest` | パーサ / 分類器パース / Slack Block の単体テスト |
| `uv run python -m watcher.debug_scrape` | 実サイトを叩いて欠損率レポート |
| `uv run python -m watcher.debug_scrape --from-html listing.html --detail-html detail.html` | 保存済みHTMLでオフライン解析 |
| `uv run python -m watcher.offline_demo --listing tests/fixtures/listing_sample.html --detail tests/fixtures/detail_sample.html` | パイプライン全体（分類器・DM・Slackペイロード生成）をモックで一気通貫実行 |
| `uv run python -m watcher.backfill_dm --dry-run` | DM 草案が未生成の対象 listing を列挙（priority 仕様変更時のバックフィル確認） |
| `uv run python -m watcher.backfill_dm` | 上記対象に対して実際に DM 生成→保存 |
| `uv run python -m watcher.backfill_sheets --dry-run` | スプシ未登録の listing (priority S/A/B) を列挙 |
| `uv run python -m watcher.backfill_sheets` | 上記対象を Google Sheets に送信（重複は Apps Script 側で弾く） |
| `uv run python -m watcher.count_jmty` | ジモティ全体の listing 数を keyword 別に計測（詳細fetchなし） |
| `uv run python -m watcher.bulk_backfill --dry-run` | ジモティ全件を巡回し、未登録の listing 数を表示 |
| `uv run python -m watcher.bulk_backfill` | 上記をすべて取り込む（詳細fetch + Claude分類 + DM生成 + Sheets + Slack）|
| `uv run python scripts/preview_slack.py [--modal] [--out preview.json]` | Slack Block Kit Builder用JSON生成 |
| `uv run python scripts/validate_sql.py` | sql/schema.sql の静的検証 |
| `uv run python scripts/estimate_cost.py` | Claude API 月額コスト試算 |
| `uv run ruff check watcher tests scripts` | Lint |

詳しい構築手順は `SETUP.md` 参照。

## 運用メモ

- **通知優先度**: S/A/B のみ Slack に投下。C（非トレーラーハウス）は DB に残すだけ。
- **DM 自動送信はしない**: 必ず人間がモーダルで内容を確認し、コピペでジモティに貼り付けて送信する。
- **レート制限**: 1リクエスト毎に約2.5秒 sleep。一覧→詳細で 1 件あたり 4〜6 秒。
- **robots.txt チェック**: 起動時に `/all/` 配下の Disallow を確認。
- **コスト**: Claude API で月2,000〜4,000円想定。Supabase / GitHub Actions / Vercel は無料枠内。

## 既知の制限（PoC スコープ）

- 一覧ページは 1 ページ目のみ（上位 ~30 件）。ページネーション未対応。
- 監視キーワードは 1 つのみを既定にしている（`モバイルハウス`, `タイニーハウス`, `キャンピングトレーラー` 等は追加拡張）。
- Slack 側でコピー済みの DM 文の実送信確認は不可（手動）。
- 画像は最大 3 枚を base64 で Claude に渡している。サイズが大きい場合スキップ。
- 誤判定は運用しつつプロンプト調整する前提。`classifications.raw_response` に JSON 全文を保存しているので後追い可能。

## ディレクトリ

```
.
├── .github/workflows/
│   ├── watcher.yml                 # 毎時cron
│   └── ci.yml                      # push毎にruff+pytest+SQL検証
├── handler/
│   ├── api/slack_interactive.py    # Vercel Serverless
│   ├── vercel.json
│   └── requirements.txt
├── scripts/
│   ├── preview_slack.py            # Slack Block Kit Builder用JSON
│   ├── validate_sql.py             # スキーマ静的検証
│   └── estimate_cost.py            # 月額コスト試算
├── sql/schema.sql                  # Supabaseスキーマ
├── tests/
│   ├── fixtures/                   # 合成HTMLサンプル
│   └── test_*.py                   # pytest
├── SETUP.md                        # 構築手順書
├── watcher/
│   ├── main.py                     # エントリポイント
│   ├── config.py
│   ├── models.py
│   ├── scraper.py
│   ├── classifier.py
│   ├── dm_generator.py
│   ├── slack_notifier.py
│   ├── db.py
│   ├── anthropic_utils.py
│   ├── debug_scrape.py             # スクレイパー単体デバッグCLI
│   ├── offline_demo.py             # パイプライン全体ドライラン
│   └── prompts/
│       ├── classifier.txt
│       └── dm_generator.txt
├── pyproject.toml
├── .env.example
└── README.md
```

## 今後の拡張

- ヤフオク RSS 監視 / メルカリ（Playwright）追加
- 返信率が高い DM 文パターンの学習ループ
- 仕入れ後の TRAILER HOUSE SECOND HAND 自動掲載連携
