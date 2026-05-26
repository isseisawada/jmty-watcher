# SETUP.md — second-hand-watcher 構築手順

ゼロから本番稼働まで30〜60分の想定。

---

## 0. 事前準備

| 必要なもの | 入手先 |
| --- | --- |
| GitHub アカウント | <https://github.com> |
| Supabase アカウント | <https://supabase.com> |
| Anthropic API キー | <https://console.anthropic.com> |
| Slack ワークスペース管理権限 | 既存のワークスペース |
| Vercel アカウント | <https://vercel.com> |
| 手元PC | Python 3.11+ |

---

## 1. ローカル環境の構築

```bash
git clone <repo-url>
cd jmty-watcher
git checkout claude/trailer-house-watcher-poc-XuHJk

# uv のインストール（未導入なら）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 依存関係を入れる
uv sync --group dev

# 動作確認: テスト全通過すればOK
uv run pytest
```

オフラインでパイプライン動作確認:

```bash
uv run python -m watcher.offline_demo \
  --listing tests/fixtures/listing_sample.html \
  --detail tests/fixtures/detail_sample.html
```

---

## 2. Supabase

1. <https://supabase.com/dashboard> で **New Project** → 任意の名前。**Database Password** を控える。
2. プロジェクト作成後、左メニュー **SQL Editor** を開く。
3. 本リポジトリの `sql/schema.sql` の内容を全コピペして **Run**。
4. 左メニュー **Settings → API** から以下を控える:
   - **Project URL** （`https://xxxxx.supabase.co`） → `SUPABASE_URL`
   - **service_role** key （`eyJhb...`） → `SUPABASE_SERVICE_KEY`

⚠️ `service_role` key は RLS を無視できる強力なキー。GitHub Secrets/Vercel Env にのみ置く。コードや公開リポにcommitしない。

### 動作確認

`Table Editor` で `jmty_listings`, `classifications`, `dm_drafts`, `outreach_log` の4テーブルが見えればOK。

---

## 3. Anthropic API

1. <https://console.anthropic.com> → **API Keys** → **Create Key**。
2. キー名は適当 (`second-hand-watcher` 等)。生成後の `sk-ant-...` を控える → `ANTHROPIC_API_KEY`。
3. 初回利用なら **Billing** で支払い情報を登録。月3000〜5000円程度のデポジットでPoC期間は足りる。

---

## 4. Slack App

### 4.1 アプリ作成

1. <https://api.slack.com/apps> → **Create New App** → **From scratch**
2. App Name: `second-hand-watcher`、Workspace を選択 → **Create App**

### 4.2 OAuth scopes

左メニュー **OAuth & Permissions**:

- **Bot Token Scopes** に以下を追加:
  - `chat:write`
  - `chat:write.public`
  - `commands` （将来 slash command を使う場合）

**Install to Workspace** → 承認 → 表示される **Bot User OAuth Token** (`xoxb-...`) を控える → `SLACK_BOT_TOKEN`。

### 4.3 Signing Secret

**Basic Information → App Credentials** から **Signing Secret** を **Show** → 控える → `SLACK_SIGNING_SECRET`。

### 4.4 Interactivity（ボタン用、 Vercel デプロイ後に設定）

ステップ5で Vercel デプロイ後に戻ってきて設定。

### 4.5 通知先チャンネル

Slack で `#second-hand-watcher` チャンネルを作る (private/public どちらでも)。チャンネル右クリック → **View channel details** → 一番下のチャンネル ID をコピー → `SLACK_CHANNEL_ID`。
Bot をチャンネルに招待: `/invite @second-hand-watcher`

---

## 5. Vercel デプロイ（Slack インタラクティブハンドラ）

### 5.1 Vercel CLI

```bash
npm i -g vercel
cd handler
vercel login
vercel
```

対話で:
- Set up and deploy → **Y**
- Which scope → 自分のアカウント
- Link to existing project → **N**
- What's your project's name → `second-hand-watcher-slack` 等
- In which directory is your code located → **`./`** （カレント）

初回は Preview デプロイ。本番化:

```bash
vercel --prod
```

URL（例: `https://second-hand-watcher-slack.vercel.app`）が出る。

### 5.2 環境変数

```bash
vercel env add SLACK_BOT_TOKEN production
vercel env add SLACK_SIGNING_SECRET production
vercel env add SUPABASE_URL production
vercel env add SUPABASE_SERVICE_KEY production
vercel --prod   # 再デプロイ
```

### 5.3 Slack App に Request URL を設定

1. <https://api.slack.com/apps> → 自分のアプリ → **Interactivity & Shortcuts**
2. **Interactivity** を **On**
3. **Request URL** に以下を設定:
   ```
   https://second-hand-watcher-slack.vercel.app/api/slack/interactive
   ```
4. **Save Changes**

### 5.4 接続テスト

`https://second-hand-watcher-slack.vercel.app/api/slack/interactive` を GET でブラウザアクセス → `slack interactive handler ok` が返ればOK。

---

## 6. GitHub Secrets / Variables

1. リポジトリ → **Settings → Secrets and variables → Actions**
2. **New repository secret** で以下を登録:

   | Name | Value |
   | --- | --- |
   | `ANTHROPIC_API_KEY` | ステップ3で控えた値 |
   | `SUPABASE_URL` | ステップ2で控えた値 |
   | `SUPABASE_SERVICE_KEY` | ステップ2で控えた値 |
   | `SLACK_BOT_TOKEN` | ステップ4.2で控えた値 |
   | `SLACK_CHANNEL_ID` | ステップ4.5で控えた値 |

3. **Variables** タブで任意の上書き値を登録（PoC期間は不要）:
   - `WATCHER_MAX_DETAILS_PER_RUN`: `30`
   - `WATCHER_SEARCH_KEYWORDS`: `トレーラーハウス,モバイルハウス`

---

## 7. 初回動作確認

### 7.1 手動実行

リポジトリ → **Actions** → **Second Hand Watcher** → **Run workflow** → ブランチを `claude/trailer-house-watcher-poc-XuHJk` にして **Run**。

ログを見て:
- `parsed N listings from listing page` が出ているか
- `classified article=... priority=...` が出ているか
- `Slack postMessage failed` が出ていないか

Supabase の `jmty_listings` テーブルに行が増えているか確認。

### 7.2 Slack 通知の見た目

priority S/A/B の出品が見つかれば自動で投下される。投下されない場合（全部 priority C 等）、`scripts/preview_slack.py` で擬似的に確認:

```bash
uv run python scripts/preview_slack.py --out preview.json
# preview.json の中身を https://app.slack.com/block-kit-builder にペースト
```

### 7.3 ボタンの動作

実際に通知が来たら:
1. **✉️ DM文を見る** → モーダルが開けばVercelハンドラ正常
2. **🙅 スルー** → 元メッセージ先頭に「🙅 スルー済み」表示、Supabase の `outreach_log` に `decision='rejected'`

---

## 8. cron稼働

GitHub Actions の `.github/workflows/watcher.yml` は `cron: '0 22 * * *'` (UTC 22:00 = JST 07:00、毎日1回) で自動稼働中。
- 頻度を上げたい場合: cron 表現を `0 */6 * * *` 等に変更
- 一旦停止する場合: Actions タブの該当workflow → **Disable workflow**

---

## 9. トラブルシュート

| 症状 | 原因候補 | 対処 |
| --- | --- | --- |
| Actions で 403 Forbidden | GitHub Runner IP がジモティに弾かれている | ローカルでテスト → Vercel CronやFly.io等の住宅IPに近い実行基盤に移行検討 |
| すべて priority=C | セレクタが古い or AI判定の閾値ズレ | `debug_scrape --save-html` で実HTML確認、prompts/classifier.txt 微調整 |
| Slack で「dispatch_failed」 | Vercel ハンドラの 3秒以内応答に失敗 | Vercel ログ確認、views_open等の長い処理は非同期化検討 |
| `outreach_log` に行が増えない | 署名検証失敗 | Vercel Env の `SLACK_SIGNING_SECRET` を再設定、Vercel デプロイ確認 |
| Anthropic 429 | レートリミット | tenacity 退避中だが、頻度を `cron '0 */2 * * *'` 等に調整 |

---

## 10. 撤収

PoC終了時:
- GitHub Actions: workflow を Disable
- Vercel: プロジェクト削除
- Slack App: <https://api.slack.com/apps> から削除
- Supabase: プロジェクト一時停止 → 必要に応じてデータエクスポート
- Anthropic: API キー失効
